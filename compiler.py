#!/usr/bin/env python

import os
import platform
import shutil
import sys
from pathlib import Path

import docker
import typer
import yaml
from colorama import Fore, Style
from docker import DockerClient
from docker.models.images import Image
from docker.errors import ImageNotFound, APIError, NotFound, DockerException


def get_architecture():
    if hasattr(os, "uname"):
        return os.uname().machine
    else:
        return "x86_64" if platform.uname().machine == "AMD64" else None


ARCH = get_architecture()


def get_list_of_packages():
    path = Path.cwd() / "packages.yml"
    contents = path.read_text(encoding="utf-8")
    parsed = yaml.load(contents, Loader=yaml.Loader)
    pkgs = []
    for package in parsed["packages"]:
        if isinstance(package, dict):
            pkgs.append(package)
        elif isinstance(package, str):
            pkgs.append({"package": package, "dependencies": []})
        else:

            print(f"{Fore.YELLOW}Warning{Fore.WHITE}: Ignoring package {Fore.MAGENTA}{package}{Fore.WHITE} "
                  f"because its not a dict or string{Style.RESET_ALL}")
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


def build_package(docker_client: DockerClient, image: Image, package_info: dict | str, print_logs: bool = True):
    package = package_info["package"]
    dependencies = package_info["dependencies"]

    print(f"{Fore.WHITE}Building package {Fore.MAGENTA}{package}{Fore.WHITE}...{Style.RESET_ALL}")

    packages_dir = Path.cwd() / "packages" / package
    packages_dir.mkdir(parents=True, exist_ok=True)

    volumes = {
        str(packages_dir): {
            "bind": "/home/builder/pkg",
        },
    }

    for dependency in dependencies:
        dep_dir = Path.cwd() / "packages" / dependency
        volumes[str(dep_dir)] = {
            "bind": f"/home/builder/deps/{dependency}",
            "mode": "ro",
        }

    params = f"{package} {' '.join(dependencies)}"
    name = f"archbuilder-{package}"

    try:
        docker_client.containers.get(name).remove(force=True)
        print(f"{Fore.YELLOW}Warning{Fore.WHITE}: Deleted existing container {Fore.BLUE}{name}{Fore.WHITE}"
              f" for package {Fore.MAGENTA}{package_info}{Fore.WHITE}{Style.RESET_ALL}")
    except NotFound:
        pass

    try:
        container = docker_client.containers.run(image, f"/home/builder/build.sh {params}",
                                                 name=name, detach=True, volumes=volumes)
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


def build_repo(docker_client: DockerClient, image: Image, packages: list[str]):
    try:
        docker_client.containers.get("archbuilder-repobuilder").remove(force=True)
        print(f"{Fore.YELLOW}Warning{Fore.WHITE}: Deleted existing container {Fore.BLUE}archbuilder-repobuilder{Style.RESET_ALL}")
    except NotFound:
        pass

    print(f"{Fore.WHITE}Building repository with {Fore.MAGENTA}{len(packages)}{Fore.WHITE} packages...{Style.RESET_ALL}")

    repo_dir = Path.cwd() / "repo" / ARCH

    for package in packages:
        package_dir = Path.cwd() / "packages" / package

        for file in package_dir.glob("*.pkg.tar.zst"):
            repo_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(file, repo_dir)
        for file in package_dir.glob("*.tar.gz"):
            repo_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(file, repo_dir)


    volumes = {
        str(repo_dir): {
            "bind": "/home/builder/repo",
        },
    }

    container = docker_client.containers.run(image, f"/home/builder/repo.sh lemon",
                                             name="archbuilder-repobuilder", detach=True, volumes=volumes)
    waited = container.wait()
    status_code = waited["StatusCode"]
    return status_code == 0


def main(build_docker: bool = False, build_packages: bool = False, package: str = None, print_logs: bool = False,
         create_repo: bool = False):
    if ARCH is None:
        sys.exit(f"Unsupported architecture")

    try:
        docker_client = docker.from_env()
    except DockerException as e:
        sys.exit(f"Unable to connect to Docker: {e}")

    if build_docker:
        print(f"{Fore.WHITE}Building docker image as {Fore.MAGENTA}archbuilder{Fore.WHITE}, please wait...{Style.RESET_ALL}")
        image, _ = docker_client.images.build(path=str(Path.cwd()), tag="archbuilder", rm=True, nocache=True)
    else:
        try:
            image = docker_client.images.get("archbuilder")
            print(f"{Fore.WHITE}Using existing {Fore.MAGENTA}archbuilder{Fore.WHITE} image{Style.RESET_ALL}")
        except ImageNotFound:
            sys.exit("Could not find archbuilder image, use --build to build it.")

    packages = get_specific_package(package) if package else get_list_of_packages()
    completed = []

    if build_packages:
        for package_info in packages:
            try:
                success = build_package(docker_client, image, package_info, print_logs)

                if success:
                    completed.append(package_info["package"])
            except Exception as e:
                print(f"{Fore.RED}Oh No! Docker has crashed!{Style.RESET_ALL} ({e})")
                input("Press enter to continue...")
    else:
        completed = [x["package"] for x in packages]

    if create_repo:
        build_repo(docker_client, image, completed)


if __name__ == "__main__":
    typer.run(main)
