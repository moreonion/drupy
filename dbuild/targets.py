import os, os.path
import shutil
import urllib

from . import resolver

class DirsTarget(resolver.Target):
    def dependencies(self):
        return []
    def build(self):
        self.runner.ensureDir(self.options.downloadDir)
        self.runner.ensureDir(os.path.join(self.options.installDir, self.options.projectsDir))

class BuildAllProjectsTarget(resolver.Target):
    def dependencies(self):
        return [BuildProjectTarget(self.runner, project) for project in self.runner.config.projects.keys()]
    
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
            
            if self.project.symlinks:
                self.runner.projectSymlinks(tmp, self.project.symlinks, 0)
            
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
            print("Hashes don't match: %s != %s" % (self.project.hash, oldHash))
        return oldHash != self.project.hash
    
    def __repr__(self):
        return "%s(%s)" % (self.__class__.__name__, self.name)

class DBInstallTarget(resolver.SiteTarget):
    def already_built(self):
        os.path.exists(os.path.join(self.options.installDir, self.options.documentRoot, 'sites', self.site, '/settings.php'))

    def updateable(self):
        return True

    def build(self):
        o = self.options
        config = self.runner.config.sites[self.site].config
        
        db_url = config['db-url']
        if o.db_prefix != None:
            p = db_url.rfind('/') + 1
            db_url = db_url[:p] + o.db_prefix + db_url[p:]
        
        profile = config['profile'] if 'profile' in config else 'standard'
        
        cmd = ['drush', 'si', '-y', '--sites-subdir='+self.site, '--db-url=' + db_url]
        cmd += [
            '--root='+os.path.join(o.installDir, o.documentRoot),
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

class SiteInstallTarget(resolver.SiteTarget):
    def __init__(self, runner, site):
        resolver.SiteTarget.__init__(self, runner, site)
        o = self.options
        self.target = os.path.join(o.installDir, o.documentRoot, 'sites', self.site)
        self.links = self.runner.config.sites[self.site].config['links']
    
    def dependencies(self):
        site = [] if self.site == 'all' else [SiteInstallTarget(self.runner, 'all')]
        return site + [CoreInstallTarget(self.runner), BuildAllProjectsTarget(self.runner)]
    
    def resetCache(self):
        if not self.options.opcache_reset_key:
            return
        error = None
        try:
            url = self.options.opcache_reset_url + self.options.opcache_reset_key
            urllib.request.urlopen(url)
        except urllib.error.HTTPError as e:
            error = e
        if not error:
            print("Reset cache called successfully")
        else:
            raise Exception('Failed to reset cache on %s: %s' % (url, str(error)))
    
    def build(self):
        self.runner.ensureDir(self.target)
        self.runner.projectSymlinks(self.target, self.links, 2)
        self.resetCache()

class CoreInstallTarget(resolver.Target):
    def __init__(self, runner):
        resolver.Target.__init__(self, runner)
        o = self.options
        self.source = os.path.join(o.installDir, o.projectsDir, o.coreConfig['project'])
        self.target = os.path.join(o.installDir, o.documentRoot)
        self.src_hash = os.path.join(self.source, '.dbuild-hash')
        self.tgt_hash = os.path.join(self.target, '.dbuild-hash')
    
    def already_built(self):
        return os.path.exists(self.target) and os.path.exists(self.tgt_hash)
    
    def updateable(self):
        with open(self.tgt_hash) as f_tgt:
            with open(self.src_hash) as f_src:
                return f_tgt.read() != f_src.read()
    
    def dependencies(self):
        return [BuildAllProjectsTarget(self.runner)]

    def build(self):
        protected = self.options.coreConfig['protected']
        self.runner.rsyncDirs(self.source, self.target, ['sites/*/'] + protected)
        protectedInSites = [x[len('sites/'):] for x in protected if x.startswith('sites/') and len(x)>len('sites/')]
        self.runner.rsyncDirs(self.source+'/sites', self.target+'/sites', ['*/'] + protectedInSites, onlyNonExisting=True)
        self.runner.rsyncDirs(self.source+'/sites/default', self.target+'/sites/default')
