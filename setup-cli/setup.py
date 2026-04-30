from setuptools import setup, find_packages

setup(
    name="homelab-setup",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "rich>=13.0.0",
        "click>=8.1.0",
        "paramiko>=3.4.0",
        "pyyaml>=6.0.0",
    ],
    entry_points={
        "console_scripts": [
            "homelab-setup=homelab_setup.cli:main",
        ],
    },
    python_requires=">=3.9",
)
