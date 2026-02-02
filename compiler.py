import sys
from pathlib import Path

import docker
import typer
import yaml
from colorama import Fore, Style
from docker import DockerClient
from docker.models.images import Image
from docker.errors import ImageNotFound, APIError, NotFound, DockerException


def get_list_of_packages():
    path = Path.cwd() / "packages.yml"
    contents = path.read_text(encoding="utf-8")
    parsed = yaml.load(contents, Loader=yaml.Loader)
    return parsed["packages"]


def get_package_details(package_name):
    path = Path.cwd() / "packages.yml"
    contents = path.read_text(encoding="utf-8")
    parsed = yaml.load(contents, Loader=yaml.Loader)

    for package in parsed["packages"]:
        if isinstance(package, dict):
            name = package["package"]
            dependencies = package["dependencies"]
        elif isinstance(package, str):
            name = package
            dependencies = []
        else:
            continue

        if name == package_name:
            return [*dependencies, package]

    return []


def build_package(docker_client: DockerClient, image: Image, package_info: dict | str, print_logs: bool = True):
    if isinstance(package_info, dict):
        package = package_info["package"]
        dependencies = package_info["dependencies"]
    elif isinstance(package_info, str):
        package = package_info
        dependencies = []
    else:
        print(f"{Fore.YELLOW}Warning{Fore.WHITE}: Skipping package {Fore.MAGENTA}{package_info}{Fore.WHITE} "
              f"because its not a dict or string{Style.RESET_ALL}")
        return

    print(f"{Fore.WHITE}Building package {Fore.MAGENTA}{package}{Fore.WHITE}...{Style.RESET_ALL}")

    packages_dir = Path.cwd() / ".repo" / package
    packages_dir.mkdir(parents=True, exist_ok=True)

    volumes = {
        str(packages_dir): {
            "bind": "/home/builder/pkg",
        },
    }

    for dependency in dependencies:
        dep_dir = Path.cwd() / ".repo" / dependency
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
        sys.exit(f"{Fore.WHITE}Unable to build {Fore.RED}{package}{Fore.WHITE} due to an API error\n{e}")

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


def main(build: bool = False, package: str = None, print_logs: bool = False):
    try:
        docker_client = docker.from_env()
    except DockerException as e:
        print(f"Unable to connect to Docker: {e}", file=sys.stderr)
        sys.exit(1)

    if build:
        print(f"{Fore.WHITE}Building docker image as {Fore.MAGENTA}archbuilder{Fore.WHITE}, please wait...{Style.RESET_ALL}")
        image, _ = docker_client.images.build(path=str(Path.cwd()), tag="archbuilder", rm=True, nocache=True)
    else:
        try:
            image = docker_client.images.get("archbuilder")
            print(f"{Fore.WHITE}Using existing {Fore.MAGENTA}archbuilder{Fore.WHITE} image{Style.RESET_ALL}")
        except ImageNotFound:
            sys.exit("Could not find archbuilder image, use --build to build it.")

    packages = get_package_details(package) if package else get_list_of_packages()

    for package_info in packages:
        build_package(docker_client, image, package_info, print_logs)


if __name__ == "__main__":
    typer.run(main)
