"""Define build-targets."""

import os
import os.path
import shutil
import urllib

from . import resolver


class DirsTarget(resolver.Target):
    """Ensure that a directory exists."""

    def build(self):
        """Create the directory if needed."""
        o = self.options
        self.runner.ensure_dir(o.download_dir)
        self.runner.ensure_dir(os.path.join(o.install_dir, o.projects_dir))


class BuildProjectTarget(resolver.Target):
    """Target for building a project in the projects/ directory."""

    def __init__(self, runner, project):
        """Create a new build project target."""
        resolver.Target.__init__(self, runner)
        o = self.runner.options
        self.name = project
        self.project = self.runner.config.projects[project]
        self.target = os.path.join(o.install_dir, o.projects_dir, project)

    def dependencies(self):
        """Return dependencies for this build target."""
        return [DirsTarget(self.runner)]

    def build(self):
        """Download and extract the projects files."""
        target = self.target
        tmp = target + "." + self.project.hash
        delete = target + ".delete"

        try:
            self.project.build(tmp)

            with open(tmp + "/.dbuild-hash", "w", encoding="utf-8") as f:
                f.write(self.project.hash)

            if os.path.exists(target):
                os.rename(target, delete)
            os.rename(tmp, target)
            if os.path.exists(delete):
                try:
                    shutil.rmtree(delete)
                except os.OSError as e:
                    print("Failed to delete: " + delete + ": " + str(e))
        finally:
            if os.path.exists(tmp) and not self.options.debug:
                shutil.rmtree(tmp)

    def already_built(self):
        """Check if the project has already been built."""
        return os.path.exists(self.target)

    def updateable(self):
        """Check if the project definition’s hash has changed since the last build."""
        if self.project.protected:
            return False
        hashfile = self.target + "/.dbuild-hash"
        if not os.path.exists(hashfile):
            return True
        with open(hashfile, "r", encoding="utf-8") as f:
            old_hash = f.read()
        if self.options.verbose and old_hash != self.project.hash:
            msg = "Hashes don't match: {} != {}"
            print(msg.format(self.project.hash, old_hash))
        return old_hash != self.project.hash

    def __repr__(self):
        """Return a string representation of this target."""
        return f"{self.__class__.__name__}({self.name})"


class DBInstallTarget(resolver.SiteTarget):
    """Target that represents drush site-install."""

    def already_built(self):
        """Check if a settings.py was created already."""
        os.path.exists(
            os.path.join(
                self.options.install_dir,
                self.options.document_root,
                "sites",
                self.site,
                "/settings.php",
            )
        )

    def updateable(self):
        """Mark this target as always updateable."""
        return True

    def build(self):
        """Run drush db-install for a site."""
        o = self.options
        config = self.runner.config.sites[self.site].config

        db_url = config["db-url"]
        if o.db_prefix is not None:
            p = db_url.rfind("/") + 1
            db_url = db_url[:p] + o.db_prefix + db_url[p:]

        profile = config["profile"]

        cmd = ["si", "-y", "--sites-subdir=" + self.site, "--db-url=" + db_url]
        cmd += [
            "--root=" + os.path.join(o.install_dir, o.document_root),
            "--account-mail=" + config["account-mail"],
            "--site-name=" + config["site-name"],
            "--site-mail=" + config["site-mail"],
            profile,
            'install_configure_form.update_status_module="array()"',
        ]
        if self.options.debug:
            cmd.append("--debug")
        if self.options.devel:
            cmd.append("mo_devel_flag=TRUE")

        self.runner.drush(cmd)

    def dependencies(self):
        """Return dependencies for this build target."""
        return [SiteInstallTarget(self.runner, self.site)]


class ProfileInstallTarget(resolver.Target):
    """Target for managing a profile symlink."""

    def __init__(self, runner, profile):
        """Create a new profile install target."""
        super().__init__(runner)
        o = self.options
        self.profile = profile
        self.target = os.path.join(o.install_dir, o.document_root, "profiles")
        self.source = self.runner.config.config["core"]["profiles"][profile]
        self.project = self.source
        if "/" in self.project:
            self.project = self.project[: self.project.find("/")]

    def dependencies(self):
        """Return dependencies for this build target."""
        return [CoreInstallTarget(self.runner), BuildProjectTarget(self.runner, self.project)]

    def build(self):
        """Create symlinks in the profiles folder."""
        if self.profile not in ("minimal", "standard", "testing"):
            links = {self.profile: self.source}
            self.runner.project_symlinks(self.target, links, 1)


class SiteBuildTarget(resolver.SiteTarget):
    """Trigger the build of all projects needed by the site."""

    def dependencies(self):
        """Return dependencies for this build target."""
        targets = [CoreBuildTarget(self.runner)]

        if self.site != "all":
            targets.append(SiteBuildTarget(self.runner, "all"))

        # Depend on all projects this site links to.
        site = self.runner.config.sites[self.site]
        for project in site.projects():
            targets.append(BuildProjectTarget(self.runner, project))

        return targets


class ResetCacheTarget(resolver.Target):
    """Reset the PHP opcache.

    PHP’s opcache doesn’t detect changed symlinks as changes to the files. Without the explicit
    opcache clear PHP might keep executing scripts from the old folder.
    """

    def __init__(self, runner, sites):
        """Create a new reset cache target."""
        super().__init__(runner)
        self.sites = sites

    def dependencies(self):
        """Return dependencies for this build target."""
        return [SiteInstallTarget(self.runner, s) for s in self.sites]

    def build(self):
        """Call the configured opcache reset URL."""
        o = self.options
        if not o.opcache_reset_key:
            return
        try:
            url = o.opcache_reset_url + o.opcache_reset_key
            urllib.request.urlopen(url)  # pylint: disable=consider-using-with
            print("Reset cache called successfully")
        except urllib.error.HTTPError as exc:
            # pylint: disable=broad-exception-raised
            raise Exception(f"Failed to reset cache on {url}: {exc}") from exc


class SiteInstallTarget(resolver.SiteTarget):
    """Create the site folder and the project symlinks."""

    def __init__(self, runner, site):
        """Create a new site install target."""
        resolver.SiteTarget.__init__(self, runner, site)
        o = self.options
        self.target = os.path.join(o.install_dir, o.document_root, "sites", self.site)
        self.links = self.runner.config.sites[self.site].config["links"]

    def dependencies(self):
        """Return dependencies for this build target."""
        targets = [
            CoreInstallTarget(self.runner),
            SiteBuildTarget(self.runner, self.site),
        ]
        if self.site != "all":
            targets.append(SiteInstallTarget(self.runner, "all"))

            profile = self.runner.config.sites[self.site].profile()
            if profile:
                targets.append(ProfileInstallTarget(self.runner, profile))
        return targets

    def build(self):
        """Create the site directory and all project symlinks."""
        self.runner.ensure_dir(self.target)
        self.runner.project_symlinks(self.target, self.links, 2)


class CoreBuildTarget(resolver.Target):
    """Extract the Drupal core tarball and apply patches."""

    def dependencies(self):
        """Return dependencies for this build target."""
        project = self.runner.config.config["core"]["project"]
        return [BuildProjectTarget(self.runner, project)]


class CoreInstallTarget(resolver.Target):
    """Copy the Drupal core files to the tree."""

    def __init__(self, runner):
        """Create the core install target install."""
        resolver.Target.__init__(self, runner)
        o = self.options
        self.source = os.path.join(o.install_dir, o.projects_dir, o.core_config["project"])
        self.target = os.path.join(o.install_dir, o.document_root)
        self.src_hash = os.path.join(self.source, ".dbuild-hash")
        self.tgt_hash = os.path.join(self.target, ".dbuild-hash")

    def already_built(self):
        """Check if there is already a Drupal tree at the target location."""
        return os.path.exists(self.target) and os.path.exists(self.tgt_hash)

    def updateable(self):
        """Check if the built Drupal tree’s hash differes from the installed one."""
        with open(self.tgt_hash, encoding="utf-8") as f_tgt:
            with open(self.src_hash, encoding="utf-8") as f_src:
                return f_tgt.read() != f_src.read()

    def dependencies(self):
        """Return dependencies for this build target."""
        return [CoreBuildTarget(self.runner)]

    def build(self):
        """Copy the built Drupal tree using rsync."""
        rsync = self.runner.rsync_dirs
        protected = self.options.core_config["protected"]
        # Sync core but keep sites and profile symlinks.
        profiles = self.runner.config.config["core"]["profiles"]
        excludes = ["profiles/" + x for x in profiles]
        rsync(self.source, self.target, ["sites/*/"] + excludes + protected)
        protected_in_sites = [
            x[len("sites/") :]
            for x in protected
            if x.startswith("sites/") and len(x) > len("sites/")
        ]
        rsync(
            self.source + "/sites",
            self.target + "/sites",
            ["*/"] + protected_in_sites,
            only_non_existing=True,
        )
        rsync(self.source + "/sites/default", self.target + "/sites/default")
