dbuild.py
=========

A multisite capable Drupal site-builder based on JSON-recipes.

Features
--------

* Download and extract packages, prepare a Drupal tree and run "drush site-install" all from the same set of configuration files.
* Package lists and site-configurations are pure JSON (ie. easy machine-generateable).
* configuration files can "include" other json-files (even remote files).
* Built-in support for multisite installations (optimized for sharing code in a manageable way).
* Install files from: git repositores, tarballs, local directories, copy files, patches

Requirements
------------

* Python3
* git
* drush (for site-install)

