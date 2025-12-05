import sys
from pathlib import Path

import docker
import typer
import yaml
from colorama import Fore, Style
from docker.errors import ImageNotFound, APIError


def get_list_of_packages():
    path = Path.cwd() / "packages.yml"
    contents = path.read_text(encoding="utf-8")
    parsed = yaml.load(contents, Loader=yaml.Loader)
    return parsed["packages"]


def main(build: bool = False):
    docker_client = docker.from_env()

    if build:
        print(f"{Fore.WHITE}Building docker image as {Fore.MAGENTA}archbuilder{Fore.WHITE}, please wait...{Style.RESET_ALL}")
        image, _ = docker_client.images.build(path=str(Path.cwd()), tag="archbuilder", rm=True, nocache=True)
    else:
        try:
            image = docker_client.images.get("archbuilder")
            print(f"{Fore.WHITE}Using existing {Fore.MAGENTA}archbuilder{Fore.WHITE} image{Style.RESET_ALL}")
        except ImageNotFound:
            sys.exit("Could not find archbuilder image, use --build to build it.")

    for package in get_list_of_packages():
        print(f"{Fore.WHITE}Building package {Fore.MAGENTA}{package}{Fore.WHITE}...{Style.RESET_ALL}")

        packages_dir = Path.cwd() / ".repo" / package
        packages_dir.mkdir(parents=True, exist_ok=True)

        volumes = {
            str(packages_dir): {
                "bind": "/home/builder/pkg",
            },
        }

        try:
            container = docker_client.containers.run(image, f"/home/builder/build.sh {package}", name=f"archbuilder-{package}",
                                                     detach=True, volumes=volumes)
        except APIError as e:
            sys.exit(f"{Fore.WHITE}Unable to build {Fore.RED}{package}{Fore.WHITE} due to an API error\n{e}")

        def is_container_running():
            container.reload()
            return container.status == "running" or container.status == "created"

        while is_container_running():
            logs = container.logs(stdout=True, stderr=True, stream=True)
            for log in logs:
                print(log.decode("utf-8").strip("\n"))
                if not is_container_running():
                    break


if __name__ == "__main__":
    typer.run(main)
