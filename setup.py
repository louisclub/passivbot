from setuptools import setup, find_packages
from setuptools_rust import RustExtension, Binding


def parse_requirements(filename):
    lines = []
    with open(filename, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-r") or line.startswith("-e"):
                continue
            lines.append(line)
    return lines


setup(
    name="passivbot",
    version="0.1.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    rust_extensions=[
        RustExtension("passivbot_rust", path="passivbot-rust/Cargo.toml", binding=Binding.PyO3)
    ],
    install_requires=parse_requirements("requirements-live.txt"),
    extras_require={
        "full": parse_requirements("requirements.txt"),
        "dev": ["pytest", "black", "ruff"],
    },
    entry_points={
        "console_scripts": [
            "passivbot=passivbot_cli:main",
        ],
    },
    setup_requires=["setuptools", "wheel", "setuptools-rust>=1.9.0"],
    include_package_data=True,
    zip_safe=False,
)
