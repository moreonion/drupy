import os
import os.path
import shutil
import urllib

from . import resolver

pjoin = os.path.join


class DirsTarget(resolver.Target):
    def dependencies(self):
        return []

    def build(self):
        o = self.options
        self.runner.ensureDir(o.downloadDir)
        self.runner.ensureDir(pjoin(o.installDir, o.projectsDir))
        self.runner.ensureDir(pjoin(o.installDir, 's'))


class BuildProjectTarget(resolver.Target):
    def __init__(self, runner, project):
        resolver.Target.__init__(self, runner)
        o = self.runner.options
        self.name = project
        self.project = self.runner.config.projects[project]
        self.target = os.path.join(o.installDir, o.projectsDir, project)

    def dependencies(self):
        return [DirsTarget(self.runner)]

    def build(self):
        target = self.target
        tmp = target + '.' + self.project.hash
        delete = target + '.delete'

        try:
            self.project.build(tmp)

            with open(tmp + '/.dbuild-hash', 'w') as f:
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
        hashfile = self.target + '/.dbuild-hash'
        if not os.path.exists(hashfile):
            return True
        with open(hashfile, 'r') as f:
            oldHash = f.read()
        if self.options.verbose and oldHash != self.project.hash:
            msg = "Hashes don't match: {} != {}"
            print(msg.format(self.project.hash, oldHash))
        return oldHash != self.project.hash

    def __repr__(self):
        return "%s(%s)" % (self.__class__.__name__, self.name)


class DBInstallTarget(resolver.SiteTarget):
    def __init__(self, runner, site):
        super().__init__(self, runner, site)
        o = self.options
        self.root_dir = pjoin(o.installDir, 's', self.site, o.documentRoot)
        self.site_dir = pjoin(self.root_dir, 'sites', self.site)

    def already_built(self):
        return os.path.exists(pjoin(self.site_dir, '/settings.php'))

    def updateable(self):
        return True

    def build(self):
        o = self.options
        config = self.runner.config.sites[self.site].config

        db_url = config['db-url']
        if o.db_prefix is not None:
            p = db_url.rfind('/') + 1
            db_url = db_url[:p] + o.db_prefix + db_url[p:]

        profile = config['profile']

        cmd = ['drush', 'si', '-y', '--sites-subdir='+self.site,
               '--db-url=' + db_url]
        cmd += [
            '--root='+self.root_dir,
            '--account-mail='+config['account-mail'],
            '--site-name="'+config['site-name']+'"',
            '--site-mail='+config['site-mail'],
            profile,
            'install_configure_form.update_status_module="array()"'
        ]
        if self.options.debug:
            cmd.append('--debug')
        if self.options.devel:
            cmd.append('mo_devel_flag=TRUE')

        self.runner.command(cmd, shell=False)

    def dependencies(self):
        return [SiteInstallTarget(self.runner, self.site)]


class ProfileInstallTarget(resolver.SiteTarget):
    """ Target for managing a profile symlink. """
    def __init__(self, runner, site, profile):
        super().__init__(runner, site)
        o = self.options
        self.profile = profile
        self.target = pjoin(o.installDir, 's', self.site, o.documentRoot,
                            'profiles')
        self.source = self.runner.config.sites[self.site].config['profiles'][profile]
        self.project = self.source
        if '/' in self.project:
            self.project = self.project[:self.project.find('/')]

    def dependencies(self):
        return [
            CoreInstallTarget(self.runner, self.site),
            BuildProjectTarget(self.runner, self.project)
        ]

    def build(self):
        if self.profile not in ('minimal', 'standard', 'testing'):
            links = {self.profile: self.source}
            self.runner.projectSymlinks(self.target, links, 3)


class SiteBuildTarget(resolver.SiteTarget):
    def __init__(self, runner, site):
        super().__init__(runner, site)

    def dependencies(self):
        targets = []

        if self.site != 'all':
            targets.append(SiteBuildTarget(self.runner, 'all'))

        # Depend on all projects this site links to.
        site = self.runner.config.sites[self.site]
        for project in site.projects():
            targets.append(BuildProjectTarget(self.runner, project))

        return targets


class SiteInstallTarget(resolver.SiteTarget):
    def __init__(self, runner, site):
        resolver.SiteTarget.__init__(self, runner, site)
        o = self.options
        self.target = pjoin(o.installDir, 's', self.site, o.documentRoot,
                            'sites', self.site)
        print(self.target)
        self.links = self.runner.config.sites[self.site].config['links']

    def dependencies(self):
        targets = [
            CoreInstallTarget(self.runner, self.site),
            SiteBuildTarget(self.runner, self.site),
        ]
        if self.site != 'all':
            targets.append(SiteAllInstallTarget(self.runner, self.site))

            for profile in self.runner.config.sites[self.site].profiles:
                targets.append(ProfileInstallTarget(self.runner, self.site, profile))
        return targets

    def resetCache(self):
        o = self.options
        if not o.opcache_reset_key:
            return
        try:
            url = o.opcache_reset_url + o.opcache_reset_key
            urllib.request.urlopen(url)
            print("Reset cache called successfully")
        except urllib.error.HTTPError as e:
            raise Exception('Failed to reset cache on %s: %s' % (url, str(e)))

    def build(self):
        self.runner.ensureDir(self.target)
        self.runner.projectSymlinks(self.target, self.links, 4)
        self.resetCache()


class SiteAllInstallTarget(SiteInstallTarget):
    def __init__(self, runner, site):
        super().__init__(runner, 'all')
        o = self.options
        self.target = pjoin(o.installDir, 's', self.site, o.documentRoot,
                            'sites', 'all')
        self.realsite = site

    def resetCache(self):
        pass

    def dependencies(self):
        targets = super().depenencies()
        targets[0] = CoreInstallTarget(self.runner, self.site)


class CoreInstallTarget(resolver.SiteTarget):
    def __init__(self, runner, site):
        super().__init__(runner, site)
        o = self.options
        c = self.runner.config.sites[site].config
        print(c)
        self.source = pjoin(o.installDir, o.projectsDir, c['core'])
        self.target = pjoin(o.installDir, 's', site, o.documentRoot)
        self.project = c['core']
        self.profiles = c['profiles']
        self.src_hash = os.path.join(self.source, '.dbuild-hash')
        self.tgt_hash = os.path.join(self.target, '.dbuild-hash')

    def already_built(self):
        return os.path.exists(self.target) and os.path.exists(self.tgt_hash)

    def updateable(self):
        with open(self.tgt_hash) as f_tgt:
            with open(self.src_hash) as f_src:
                return f_tgt.read() != f_src.read()

    def dependencies(self):
        return [BuildProjectTarget(self.runner, self.project)]

    def build(self):
        self.runner.ensureDir(pjoin(self.target, 'profiles'))
        self.runner.ensureDir(pjoin(self.target, 'sites'))
        links = dict(profiles=dict(), sites=dict())
        hfile = '.dbuild-hash'

        for e in os.listdir(self.source):
            if e not in ('profiles', 'sites', hfile):
                links[e] = pjoin(self.project, e)

        for e in os.listdir(pjoin(self.source, 'profiles')):
            links['profiles'][e] = pjoin(self.project, 'profiles', e)

        links['sites']['default'] = pjoin(self.project, 'sites', 'default')

        self.runner.projectSymlinks(self.target, links, 2)

        pconfig = self.runner.config.config['projects'][self.project]
        protected = pconfig['copy']
        protectedInSites = [
            x[len('sites/'):] for x in protected
            if x.startswith('sites/') and len(x) > len('sites/')
        ] + ['default']
        self.runner.rsyncDirs(self.source+'/sites', self.target+'/sites',
              ['*/'] + protectedInSites, onlyNonExisting=True)
        shutil.copyfile(pjoin(self.source, hfile), pjoin(self.target, hfile))
