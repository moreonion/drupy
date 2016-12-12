from setuptools import setup

setup(
  name='dbuild.py',
  version='0.1',
  description='Python based deployment tool for drupal',
  long_description='Fast, multisite capable drupal deployment tool',
  classifiers=[
    'Development Status :: 3 - Alpha',
    'Environment :: Console',
    'Intended Audience :: Developers',
    'Intended Audience :: System Administrators',
    'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
    'Topic :: System :: Software Distribution',
  ],
  keywords='drupal dbuild dbuild.py drush make',

  url = 'https://github.com/torotil/dbuild.py',

  packages=['dbuild'],
  entry_points = {
    'console_scripts': ['dbuild.py = dbuild.runner:main'],
  },
  include_package_data = True,
)
