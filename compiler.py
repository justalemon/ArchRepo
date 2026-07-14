#!/usr/bin/env python

import shutil
import sys
from pathlib import Path
from typing import Annotated

import docker
import yaml
from colorama import Fore, Style
from docker import DockerClient
from docker.models.images import Image
from docker.errors import ImageNotFound, APIError, NotFound, DockerException
from pick import pick
from typer import Option, run

IMAGES = {
    "amd64": "archlinux:latest",
    "arm64": "menci/archlinuxarm:latest",
    "arm": "menci/archlinuxarm:latest"
}
PACMAN_ARCH = {
    "amd64": "x86_64",
    "arm64": "aarch64",
    "arm": "armv7h"
}


def get_list_of_packages():
    path = Path.cwd() / "packages.yml"
    contents = path.read_text(encoding="utf-8")
    parsed = yaml.load(contents, Loader=yaml.Loader)
    pkgs = []
    for package in parsed["packages"]:
        if not isinstance(package, dict):
            print(f"{Fore.YELLOW}Warning{Fore.WHITE}: Ignoring package {Fore.MAGENTA}{package}{Fore.WHITE} "
                  f"because its not a dict{Style.RESET_ALL}")

        if "package" not in package:
            print(f"{Fore.YELLOW}Warning{Fore.WHITE}: Ignoring package {Fore.MAGENTA}{package}{Fore.WHITE} "
                  f"because it does not specify a package name{Style.RESET_ALL}")
        if "commit" not in package:
            print(f"{Fore.YELLOW}Warning{Fore.WHITE}: Ignoring package {Fore.MAGENTA}{package['package']}{Fore.WHITE} "
                  f"because it does not specify a commit{Style.RESET_ALL}")

        pkgs.append(package)

    return pkgs


def get_specific_package(package_name):
    packages = get_list_of_packages()

    matched = []
    match = next((x for x in packages if x["package"] == package_name), None)

    for package in packages:
        if package["package"] in match["dependencies"]:
            matched.append(package)

    matched.append(match)

    return matched


def build_package(docker_client: DockerClient, image: Image, package_info: dict, arch: str, print_logs: bool = True):
    package = package_info["package"]
    dependencies = package_info.get("dependencies", [])
    commit = package_info["commit"]

    print(f"{Fore.WHITE}Building package {Fore.MAGENTA}{package}{Fore.WHITE} for architecture "
          f"{Fore.MAGENTA}{arch}{Fore.WHITE}...{Style.RESET_ALL}")

    packages_dir = Path.cwd() / "packages" / arch / package
    packages_dir.mkdir(parents=True, exist_ok=True)

    volumes = {
        str(packages_dir): {
            "bind": "/home/builder/pkg",
        },
    }

    for dependency in dependencies:
        dep_dir = Path.cwd() / "packages" / arch / dependency
        volumes[str(dep_dir)] = {
            "bind": f"/home/builder/deps/{dependency}",
            "mode": "ro",
        }

    params = f"{package} {commit} {' '.join(dependencies)}"
    name = f"archbuilder-{package}"

    try:
        docker_client.containers.get(name).remove(force=True)
        print(f"{Fore.YELLOW}Warning{Fore.WHITE}: Deleted existing container {Fore.BLUE}{name}{Fore.WHITE}"
              f" for package {Fore.MAGENTA}{package}{Fore.WHITE}{Style.RESET_ALL}")
    except NotFound:
        pass

    try:
        container = docker_client.containers.run(image, f"/home/builder/build.sh {params}",
                                                 name=name, platform=f"linux/{arch}", detach=True, volumes=volumes)
    except APIError as e:
        print(f"{Fore.WHITE}Unable to build {Fore.RED}{package}{Fore.WHITE} due to an API error\n{e}")
        return False

    def is_container_running():
        container.reload()
        return container.status == "running" or container.status == "created"

    buffer = []

    while is_container_running():
        logs = container.logs(stdout=True, stderr=True, stream=True)
        for log in logs:
            msg = log.decode("utf-8").strip("\n")
            buffer.append(msg)

            if print_logs:
                print(msg)

            if not is_container_running():
                break

    waited = container.wait()
    status_code = waited["StatusCode"]

    if status_code != 0:
        print(f"{Fore.YELLOW}Warning{Fore.WHITE}: Unable to build package {Fore.MAGENTA}{package}{Fore.WHITE} "
              f"({status_code}) {Style.RESET_ALL}")
    else:
        print(f"{Fore.WHITE}Successfully built package {Fore.MAGENTA}{package}{Fore.WHITE}"
              f"{Style.RESET_ALL}")
        container.remove()

    log_file = packages_dir / "build.log"
    log_file.write_text("\n".join(buffer), encoding="utf-8")
    return status_code == 0


def build_repo(docker_client: DockerClient, image: Image, packages: list[str], arch: str):
    try:
        docker_client.containers.get("archbuilder-repobuilder").remove(force=True)
        print(f"{Fore.YELLOW}Warning{Fore.WHITE}: Deleted existing container {Fore.BLUE}archbuilder-repobuilder{Style.RESET_ALL}")
    except NotFound:
        pass

    print(f"{Fore.WHITE}Building repository with {Fore.MAGENTA}{len(packages)}{Fore.WHITE} packages...{Style.RESET_ALL}")

    repo_dir = Path.cwd() / "repo" / PACMAN_ARCH[arch]

    for package in packages:
        print(f"{Fore.WHITE}Processing package {Fore.MAGENTA}{package}{Fore.WHITE} for repo{Style.RESET_ALL}")
        package_dir = Path.cwd() / "packages" / arch / package

        for file in package_dir.glob("*.pkg.tar.*"):
            repo_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(file, repo_dir)
            print(f"{Fore.WHITE}Copied file {Fore.MAGENTA}{file.name}{Fore.WHITE} for package {Fore.MAGENTA}{package}{Fore.WHITE}{Style.RESET_ALL}")
        for file in package_dir.glob("*.tar.gz"):
            repo_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(file, repo_dir)
            print(f"{Fore.WHITE}Copied file {Fore.MAGENTA}{file.name}{Fore.WHITE} for package {Fore.MAGENTA}{package}{Fore.WHITE}{Style.RESET_ALL}")


    volumes = {
        str(repo_dir): {
            "bind": "/home/builder/repo",
        },
    }

    container = docker_client.containers.run(image, f"/home/builder/repo.sh lemon", name="archbuilder-repobuilder",
                                             platform=f"linux/{arch}", detach=True, volumes=volumes)
    waited = container.wait()
    status_code = waited["StatusCode"]
    return status_code == 0


def main(interactive: Annotated[bool, Option(help="Interactively asks for input. Ignores all other options.")] = False,
         build_docker: Annotated[bool, Option(help="Build a new Docker image for the chosen architecture.")] = False,
         build_packages: Annotated[bool, Option(help="Builds all packages from the index.")] = False,
         package: Annotated[str, Option(help="The single package to compile.")] = None,
         print_logs: Annotated[bool, Option(help="Prints the Docker output to the console.")] = False,
         create_repo: Annotated[bool, Option(help="Creates and/or Updates the Arch repo index.")] = False,
         arch: Annotated[str, Option(help="The Architecture to compile the packages against.")] = "amd64"):
    if arch not in IMAGES:
        sys.exit(f"Unsupported architecture")

    try:
        docker_client = docker.from_env()
    except DockerException as e:
        sys.exit(f"Unable to connect to Docker: {e}")

    all_packages = get_list_of_packages()
    packages = []

    if interactive:
        picks = pick([f"Switch Architecture (current: {arch})", "Build Docker Image", "Build Specific Package(s)",
                      "Build ALL Packages", "Build Arch Repo", "Exit"],
                            "Lemon's Arch Repository Builder", multiselect=True, min_selection_count=1)
        for _, index in picks:
            match index:
                case 0:
                    arch, _ = pick(list(IMAGES.keys()), "Select the target Architecture")
                case 1:
                    build_docker = True
                case 2:
                    pkgs = pick(list(x["package"] for x in all_packages), "Select packages to compile", multiselect=True,
                                min_selection_count=1)
                    explicit = [x[0] for x in pkgs]
                    implicit_deps = list(x["dependencies"] for x in all_packages if "dependencies" in x and x["package"] in explicit)
                    implicit = list(i for s in implicit_deps for i in s)

                    for pkg in all_packages:
                        name = pkg["package"]

                        if name in explicit or name in implicit:
                            packages.append(pkg)
                    build_packages = True
                case 3:
                    packages = [x for x in all_packages if not x.get("skip", False)]
                    build_packages = True
                case 4:
                    create_repo = True
                case 5:
                    sys.exit(0)

    if build_docker:
        print(f"{Fore.WHITE}Building docker image as {Fore.MAGENTA}archbuilder:{arch}{Fore.WHITE}, please wait...{Style.RESET_ALL}")
        image, _ = docker_client.images.build(path=str(Path.cwd()), platform=f"linux/{arch}", tag=f"archbuilder:{arch}",
                                              rm=True, nocache=True, buildargs={"BASE_IMAGE": IMAGES[arch]})
    else:
        try:
            image = docker_client.images.get(f"archbuilder:{arch}")
            print(f"{Fore.WHITE}Using existing {Fore.MAGENTA}archbuilder:{arch}{Fore.WHITE} image{Style.RESET_ALL}")
        except ImageNotFound:
            sys.exit(f"Could not find archbuilder:{arch} image. Please build the image or disable Resource Saver Mode if active.")

    completed = []

    if build_packages:
        for package_info in packages:
            try:
                success = build_package(docker_client, image, package_info, arch, print_logs)

                if success:
                    completed.append(package_info["package"])
            except Exception as e:
                print(f"{Fore.RED}Oh No! Docker has crashed!{Style.RESET_ALL} ({e})")
                input("Press enter to continue...")
    else:
        completed = [x["package"] for x in packages]

    if create_repo:
        build_repo(docker_client, image, completed, arch)


if __name__ == "__main__":
    run(main)
