FROM archlinux:latest

RUN pacman -Syu --noconfirm base-devel sudo git
RUN useradd -m builder && passwd -d builder && echo "builder ALL=(root) NOPASSWD:ALL" >> /etc/sudoers

WORKDIR /home/builder
COPY build.sh /home/builder

USER builder
