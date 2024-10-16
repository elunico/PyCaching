import setuptools

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="pycaching-elunico",
    version="1.3.2",
    author="Thomas Povinelli",
    author_email="tompov227@gmail.com",
    description="A utility for file system caching",
    long_description=long_description,
    long_description_content_type="text/markdown",
    include_package_data=True,
    url="https://github.com/elunico/PyCaching",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    packages=setuptools.find_packages(),
    python_requires=">=3.11",
    install_requires=['msgpack==1.0.7',
              'colorcodes-elunico==1.0.0',
              'requests==2.32.3']
)
