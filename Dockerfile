FROM debian:bookworm-slim

# Install necessary dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    git \
    build-essential \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Install the latest stable Rust toolchain
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"
RUN rustup default stable && rustup update

# Install rust-analyzer
RUN curl -L https://github.com/rust-analyzer/rust-analyzer/releases/latest/download/rust-analyzer-x86_64-unknown-linux-gnu.gz | gunzip -c > /usr/local/bin/rust-analyzer \
    && chmod +x /usr/local/bin/rust-analyzer

# Install SCIP
RUN env \
    TAG="v0.5.2" \
    OS="$(uname -s | tr '[:upper:]' '[:lower:]')" \
    ARCH="$(uname -m | sed -e 's/x86_64/amd64/')" \
    bash -c 'curl -L "https://github.com/sourcegraph/scip/releases/download/$TAG/scip-$OS-$ARCH.tar.gz"' \
    | tar xzf - scip \
    && mv scip /usr/local/bin/ \
    && chmod +x /usr/local/bin/scip

# Prepend /usr/local/bin to PATH to prioritize our custom tools
ENV PATH="/usr/local/bin:${PATH}"

# Create symbolic links
RUN ln -sf /usr/local/bin/rust-analyzer /usr/bin/rust-analyzer && \
    ln -sf /usr/local/bin/scip /usr/bin/scip

# Verify installations
# This should now show /usr/local/bin/rust-analyzer
RUN cargo --version && which rust-analyzer && which scip && rust-analyzer --version && scip --version

# Create and activate a Python virtual environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" 

# Set working directory to mounted volume location
WORKDIR /work

# Set default command to provide a shell with tools
CMD ["/bin/bash"]
