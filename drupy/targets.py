import os
import os.path
import shutil
import urllib

from . import resolver


class DirsTarget(resolver.Target):
    def dependencies(self):
        return []

    def build(self):
        o = self.options
        self.runner.ensure_dir(o.download_dir)
        self.runner.ensure_dir(os.path.join(o.install_dir, o.projects_dir))


class BuildProjectTarget(resolver.Target):
    def __init__(self, runner, project):
        resolver.Target.__init__(self, runner)
        o = self.runner.options
        self.name = project
        self.project = self.runner.config.projects[project]
        self.target = os.path.join(o.install_dir, o.projects_dir, project)

    def dependencies(self):
        return [DirsTarget(self.runner)]

    def build(self):
        target = self.target
        tmp = target + "." + self.project.hash
        delete = target + ".delete"

        try:
            self.project.build(tmp)

            with open(tmp + "/.dbuild-hash", "w") as f:
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
        return os.path.exists(self.target)

    def updateable(self):
        if self.project.protected:
            return False
        hashfile = self.target + "/.dbuild-hash"
        if not os.path.exists(hashfile):
            return True
        with open(hashfile, "r") as f:
            oldHash = f.read()
        if self.options.verbose and oldHash != self.project.hash:
            msg = "Hashes don't match: {} != {}"
            print(msg.format(self.project.hash, oldHash))
        return oldHash != self.project.hash

    def __repr__(self):
        return "%s(%s)" % (self.__class__.__name__, self.name)


class DBInstallTarget(resolver.SiteTarget):
    def already_built(self):
        os.path.exists(
            os.path.join(
                self.options.install_dir,
                self.options.documentRoot,
                "sites",
                self.site,
                "/settings.php",
            )
        )

    def updateable(self):
        return True

    def build(self):
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
        return [SiteInstallTarget(self.runner, self.site)]


class ProfileInstallTarget(resolver.Target):
    """Target for managing a profile symlink."""

    def __init__(self, runner, profile):
        super().__init__(runner)
        o = self.options
        self.profile = profile
        self.target = os.path.join(o.install_dir, o.document_root, "profiles")
        self.source = self.runner.config.config["core"]["profiles"][profile]
        self.project = self.source
        if "/" in self.project:
            self.project = self.project[: self.project.find("/")]

    def dependencies(self):
        return [CoreInstallTarget(self.runner), BuildProjectTarget(self.runner, self.project)]

    def build(self):
        if self.profile not in ("minimal", "standard", "testing"):
            links = {self.profile: self.source}
            self.runner.projectSymlinks(self.target, links, 1)


class SiteBuildTarget(resolver.SiteTarget):
    def __init__(self, runner, site):
        super().__init__(runner, site)

    def dependencies(self):
        targets = [CoreBuildTarget(self.runner)]

        if self.site != "all":
            targets.append(SiteBuildTarget(self.runner, "all"))

        # Depend on all projects this site links to.
        site = self.runner.config.sites[self.site]
        for project in site.projects():
            targets.append(BuildProjectTarget(self.runner, project))

        return targets


class ResetCacheTarget(resolver.Target):
    def __init__(self, runner, sites):
        super().__init__(runner)
        self.sites = sites

    def dependencies(self):
        return [SiteInstallTarget(self.runner, s) for s in self.sites]

    def build(self):
        """Call the configured opcache reset URL."""
        o = self.options
        if not o.opcache_reset_key:
            return
        try:
            url = o.opcache_reset_url + o.opcache_reset_key
            urllib.request.urlopen(url)
            print("Reset cache called successfully")
        except urllib.error.HTTPError as e:
            raise Exception("Failed to reset cache on %s: %s" % (url, str(e)))


class SiteInstallTarget(resolver.SiteTarget):
    def __init__(self, runner, site):
        resolver.SiteTarget.__init__(self, runner, site)
        o = self.options
        self.target = os.path.join(o.install_dir, o.document_root, "sites", self.site)
        self.links = self.runner.config.sites[self.site].config["links"]

    def dependencies(self):
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
        self.runner.ensure_dir(self.target)
        self.runner.projectSymlinks(self.target, self.links, 2)


class CoreBuildTarget(resolver.Target):
    def __init__(self, runner):
        super().__init__(runner)

    def dependencies(self):
        project = self.runner.config.config["core"]["project"]
        return [BuildProjectTarget(self.runner, project)]


class CoreInstallTarget(resolver.Target):
    def __init__(self, runner):
        resolver.Target.__init__(self, runner)
        o = self.options
        self.source = os.path.join(o.install_dir, o.projects_dir, o.core_config["project"])
        self.target = os.path.join(o.install_dir, o.document_root)
        self.src_hash = os.path.join(self.source, ".dbuild-hash")
        self.tgt_hash = os.path.join(self.target, ".dbuild-hash")

    def already_built(self):
        return os.path.exists(self.target) and os.path.exists(self.tgt_hash)

    def updateable(self):
        with open(self.tgt_hash) as f_tgt:
            with open(self.src_hash) as f_src:
                return f_tgt.read() != f_src.read()

    def dependencies(self):
        return [CoreBuildTarget(self.runner)]

    def build(self):
        rsync = self.runner.rsyncDirs
        protected = self.options.core_config["protected"]
        # Sync core but keep sites and profile symlinks.
        profiles = self.runner.config.config["core"]["profiles"]
        excludes = ["profiles/" + x for x in profiles]
        rsync(self.source, self.target, ["sites/*/"] + excludes + protected)
        protectedInSites = [
            x[len("sites/") :]
            for x in protected
            if x.startswith("sites/") and len(x) > len("sites/")
        ]
        rsync(
            self.source + "/sites",
            self.target + "/sites",
            ["*/"] + protectedInSites,
            onlyNonExisting=True,
        )
        rsync(self.source + "/sites/default", self.target + "/sites/default")
