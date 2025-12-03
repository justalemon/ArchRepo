from pathlib import Path

import typer
import yaml


def get_list_of_packages():
    path = Path.cwd() / "packages.yml"
    contents = path.read_text(encoding="utf-8")
    parsed = yaml.load(contents, Loader=yaml.Loader)
    return parsed["packages"]


def main():
    packages = get_list_of_packages()


if __name__ == "__main__":
    typer.run(main)
