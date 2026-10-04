from setuptools import setup, find_packages

setup(
    name="ai-reputation-guard",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "click>=8.0",
        "requests>=2.28",
    ],
    entry_points={
        "console_scripts": [
            "ai-reputation-guard=src.cli:main",
        ],
    },
    python_requires=">=3.9,<3.15",
    author="Yunare Maia",
    description="Detect AI-assisted reputation laundering on GitHub",
    license="MIT",
)
