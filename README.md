
---

# Yay - an autonomous CLI Coding Agent 

## Installation

To install the agent, simply run:

```bash
bash install.sh
```

This script will automatically set up dependencies, install required packages, and configure the environment for running the agent.

---

## Usage

The system supports two main modes:

### 1. TUI Mode (Interactive Terminal UI)

Run the agent with:

```bash
yay
```

If no arguments or piped input are provided, the system automatically launches the **TUI**.

---

### 2. Shell Mode

If you pass arguments or pipe input, the agent switches to shell mode:

```bash
yay "your task here"
```

or:

```bash
echo "fix this bug" | yay
```