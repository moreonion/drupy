from setuptools import setup

setup(
    name='drupy',
    version='0.2',
    description='Python based deployment tool for drupal',
    long_description='Fast, multisite capable drupal deployment tool',
    author='Roman Zimmermann',
    author_email='torotil@gmail.com',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Topic :: System :: Software Distribution',
    ],
    keywords='drupal drupy build',

    url='https://github.com/moreonion/drupy',
    download_url='https://github.com/moreonion/drupy/archive/v0.2.tar.gz',

    packages=['drupy'],
    entry_points={
        'console_scripts': ['drupy = drupy.runner:main'],
    },
    include_package_data=True,
)
