FROM archlinux:latest

RUN sed -i "s/^#DisableSandboxFilesystem/DisableSandbox\n#DisableSandboxFilesystem/" /etc/pacman.conf
RUN pacman -Syu --noconfirm base-devel sudo git
RUN useradd -m builder && passwd -d builder && echo "builder ALL=(root) NOPASSWD:ALL" >> /etc/sudoers

WORKDIR /home/builder
COPY scripts/build.sh /home/builder
COPY scripts/repo.sh /home/builder

USER builder
