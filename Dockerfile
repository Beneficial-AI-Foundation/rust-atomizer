FROM rust:1.74-slim as builder

# Install necessary dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install rust-analyzer
RUN curl -L https://github.com/rust-analyzer/rust-analyzer/releases/latest/download/rust-analyzer-x86_64-unknown-linux-gnu.gz | gunzip -c > /usr/local/bin/rust-analyzer \
    && chmod +x /usr/local/bin/rust-analyzer

# Clone and install SCIP
RUN env \
    TAG="v0.5.2" \
    OS="$(uname -s | tr '[:upper:]' '[:lower:]')" \
    ARCH="$(uname -m | sed -e 's/x86_64/amd64/')" \
    bash -c 'curl -L "https://github.com/sourcegraph/scip/releases/download/$TAG/scip-$OS-$ARCH.tar.gz"' \
    | tar xzf - scip \
    && mv scip /usr/local/bin/ \
    && chmod +x /usr/local/bin/scip

# Verify installations
RUN cargo --version && which rust-analyzer && which scip

# Create and activate a Python virtual environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies in the virtual environment
RUN pip3 install mysql-connector-python

# Set working directory
WORKDIR /app

# Copy the project files
COPY . .

# Build the project
RUN cargo build --release

# Run stage
FROM debian:bookworm-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-venv \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy the virtual environment from the builder stage
COPY --from=builder /opt/venv /opt/venv

# Set environment variables to use the virtual environment
ENV PATH="/opt/venv/bin:$PATH"

# Copy binaries from builder stage
COPY --from=builder /usr/local/bin/rust-analyzer /usr/local/bin/
COPY --from=builder /usr/local/bin/scip /usr/local/bin/
COPY --from=builder /app/target/release/write_atoms /usr/local/bin/
COPY --from=builder /app/scripts /app/scripts

# Set working directory
WORKDIR /work

# Set environment variables
ENV PATH="/usr/local/bin:${PATH}"

# Entry point
ENTRYPOINT ["write_atoms"]