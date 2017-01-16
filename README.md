drupy
=====

A multisite capable Drupal site-builder based on JSON-recipes.

Features
--------

* Download and extract packages, prepare a Drupal tree and run "drush site-install" all from the same set of configuration files.
* Package lists and site-configurations are pure JSON (ie. easy machine-generateable).
* configuration files can "include" other json-files (even remote files).
* Built-in support for multisite installations (optimized for sharing code in a manageable way).
* Install files from: git repositores, tarballs, local directories, copy files, patches
* Fast: if you change only one project (ie. add a patch) only this project is rebuilt.
* Use hashes to check the integrity of downloaded files.

Requirements
------------

* Python3
* git
* drush (for running site-install)
* rsync
* A symlink capable file-system

FAQ
---

*   **Why not simply use drush make?**
    For our multi-site setup we'd like a directory structure that looks something like:

        projects/              # packages
          module1-7.x-1.0/     # code of module1
          module1-7.x-2.1/     # another version of module1
          somesite/            # code of the custom somesite projects
          theproject/          # another custom project with a install_profile
        htdocs/                # drupal-root
          profiles/
            theproject/ -> ../../projects/theproject
            minimal/
            standard/
            testing/
          sites/
            somesite/
              modules/         # symlinks to projects in the projects sub-folder
                contrib/       # only one copy of a module per version.
                  module1 -> ../../../../../projects/module1-7.x-1.0
                  …
              themes/
                somesite-modules -> ../../../../projects/somesite/modules
                contrib/
                  theme1 -> ../../../../../projects/theme1-7.x-1.0
                  …
            othersite/
              modules/
                contrib/       # allow different versions of a module per site
                  module1 -> ../../../../../projects/module1-7.x-2.0
          
    Directory layouts like this seems rather cumbersome with drush make which seems to be a bit biased towards a one-drupal-tree-per-site approach of hosting.

*   **Why not use sites/all/ for code-sharing?**
    sites/all/ doesn't allow us to update modules site by site. If an module has an update-hook (ie. brings down your site until drush updb is run) you have to update the module-code. Then you need to run drush updb in all sites to bring them online again. So the mean down-time for a site is: n/2. With lots of sites this can take quite some time.
*   **Why care for code sharing at all?**
    Sharing the code for modules means that our opcode cache needs to hold only one copy of a file instead of one per site.

