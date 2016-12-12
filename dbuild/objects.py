from copy import deepcopy, copy
import os.path
import urllib.parse
import urllib.request
import hashlib
import json
import setuptools.archive_util
import shutil
import collections
from glob import glob

def addDefaults(config, defaults):
    queue = [(config, defaults)]
    
    while len(queue) > 0:
        c, d = queue.pop(0)
        for k in d.keys():
            if k in c:
                if type(c[k]) in (collections.OrderedDict, dict) and type(d[k]) in (collections.OrderedDict, dict):
                    queue.append((c[k], d[k]))
            else:
                c[k] = deepcopy(d[k])

class Config:
    defaults = {}
    def __init__(self, runner, path):
        self.runner = runner
        self.path = path
        self.config = self.readConfig()
    def readConfig(self):
        o = self.runner.options
        files = [(None, self.path)]
        data = collections.OrderedDict()
        while (len(files) > 0):
            relTo, path = files.pop(0)
            path = self.runner.getDownloader({'url': path}).download(relTo, o.downloadDir).localpath()
            
            with open(path) as configfile:
                try:
                    new_data = json.load(configfile, object_pairs_hook=collections.OrderedDict)
                except ValueError as e:
                    raise ValueError('Error while parsing %s: %s' % (path, str(e)))
            if 'includes' in new_data:
                includes = new_data['includes']
                del new_data['includes']
                relTo = os.path.dirname(path)
                for inc in includes:
                    files.append((relTo, inc))
            addDefaults(data, new_data)
        addDefaults(data, self.defaults)
        return data
    

class Tree(Config):
    defaults = {
        'documentRoot': 'htdocs',
        'projectsDir': 'projects',
        'downloadDir': 'downloads',
        'core': {
            'project': None,
            'profiles': {},
            'protected': []
        },
        'projects': {},
    }
    def __init__(self, runner, path):
        Config.__init__(self, runner, path)
        core = self.config['core']
        if core['project'] and core['project'] in self.config['projects']:
            addDefaults(self.config['projects'][core['project']], {'symlinks': { 'profiles': core['profiles'] }})
        self.projects = collections.OrderedDict()
        for dirname, config in self.config['projects'].items():
            config['dirname'] = dirname
            self.projects[dirname] = runner.getProject(config)
        
        self.sites = {}
        for configpath in glob(os.path.dirname(path) + '/*.site.json'):
            basename = os.path.basename(configpath)
            site = basename[:basename.find('.')]
            self.sites[site] = Site(self.runner, site, configpath)


class Site(Config):
    defaults = {
        'profile': 'standard',
        'db-url': None,
        'site-mail': None,
        'site-name': None,
        'account-mail': None,
        'links': {}
    }
    def __init__(self, runner, name, path):
        Config.__init__(self, runner, path)
        self.site = name
        if not self.config['db-url']:
            self.config['db-url'] = 'dpl:dplpw@localhost/' + name
        
class TypedFactory:
    def __init__(self, runner, name, types):
        self.runner, self.name, self.types = runner, name, types
    def produce(self, config):
        for t in self.types:
            try:
                obj = t(self.runner, config)
                if obj.isValid():
                    return obj
            except ValueError as e:
                """Allow implementations to err out of non-applicable configs"""
                if self.runner.options.verbose:
                    print('Not a %s: %s' % (t.__name__, e))
        raise Exception("No matching %s for input: %s" % (self.name, config))

class Downloader:
    def __init__(self, runner, config):
        self.runner = runner
        self.url = config['url']
        self.hash = None
        if self.url.find('#') != -1:
            self.url, self.hash = self.url.split('#', 1)
        self.scheme = urllib.parse.urlparse(self.url).scheme
    def download(self, relTo, store):
        return self
    def localpath(self):
        return self.url
    def isValid(self):
        return True
    def convertToMake(self, pfx, patchShortHand=False):
        if patchShortHand:
            print("%s = %s" % (pfx, self.url))
        else:
            print("%s[type] = file" % (pfx))
            print("%s[url] = %s" % (pfx, self.url))
        

class ScmNoopDownloader(Downloader):
    def __init__(self, runner, config):
        hasScmType = 'type' in config and config['type'] in ['git']
        hasRevisionOrBranch = 'revision' in config or 'branch' in config
        if not hasScmType and not hasRevisionOrBranch:
            raise ValueError('This is not a SCM ressource')
        Downloader.__init__(self, runner, config)
        self.scmType = 'git'
        self.branch = config['branch'] if 'branch' in config else False
        self.revision = config['revision'] if 'revision' in config else False
    def convertToMake(self, pfx, patchShortHand=False):
        print(pfx + '[type] = ' + self.scmType)
        print(pfx + '[url] = ' + self.url)
        if self.branch:
            print(pfx + '[branch] = ' + self.branch)
        if self.revision:
            print(pfx + '[revision] = ' + self.revision)
    

class LocalDownloader(Downloader):
    def download(self, relTo, store):
        if not relTo or os.path.isabs(self.url):
            self.path = self.url
        else:
            self.path = os.path.join(relTo, self.url)
        return self
    def localpath(self):
        return self.path
    def isValid(self):
        return not self.scheme

class UrllibDownloader(Downloader):
    def __init__(self, runner, config):
        Downloader.__init__(self, runner, config)
    def download(self, relTo, store):
        self.path = os.path.join(store, self.url.replace('/', '-').replace(':', '-'))
        if os.path.exists(self.path):
            if not self.hash or self.getHash() == self.hash:
                return
            else:
                os.unlink(self.path)
        if self.runner.options.verbose:
            print("Downloading %s" % self.url)
        try:
            f = urllib.request.urlopen(self.url)
        except urllib.error.HTTPError as e:
            raise Exception('Error during download of %s: %s' % (self.url, str(e)))
        with open(self.path, 'wb') as target:
            target.write(f.read())
        if self.hash:
            actual_hash = self.getHash()
            if self.hash != actual_hash:
                raise Exception("Hash of file downloaded from %s wrong: %s instead of %s" % (self.url, actual_hash, self.hash))
        return self
    def getHash(self):
        with open(self.path, 'rb') as f:
            return hashlib.sha1(f.read()).hexdigest()
    def localpath(self):
        return self.path
    def isValid(self):
        return self.scheme in ['http', 'https', 'ftp'] and not self.url.endswith('.git')

class Ressource:
    def __init__(self, runner, config):
        self.runner = runner
        self.config  = deepcopy(config)
        if type(self.config) is str:
            self.config = {'url': config}
    def download(self):
        o = self.runner.options
        downloader = self.runner.getDownloader(self.config)
        downloader.download(o.sourceDir, o.downloadDir)
        self.config['localpath'] = downloader.localpath()
    def applyTo(self, target):
        if 'devel' in self.config and self.config['devel'] != self.runner.options.devel:
            "Don't apply ressources that are production or devel only"
            return
        applier = self.runner.getApplier(self.config)
        applier.applyTo(target)
    def convertToMake(self, pfx, patchShortHand=False):
        if 'purpose' in self.config:
            comment = '; ' + self.config['purpose']
            if 'link' in self.config:
                comment += ' - ' + self.config['link']
            print(comment)
        downloader = self.runner.getDownloader(self.config)
        downloader.convertToMake(pfx, patchShortHand)

class Applier:
    def __init__(self, runner, config):
        self.runner = runner
        self.path = config['localpath']
        self.type = config['type'] if 'type' in config else None
        self.config = config

class TarballExtract(Applier):
    def applyTo(self, target):
        def extractFilter(name, destination):
            if name.find('/') >= 0:
                return target + '/' + name[name.find('/')+1:]
            else:
                return False
        setuptools.archive_util.unpack_archive(self.path, target, progress_filter=extractFilter)    
    def isValid(self):
        if self.type == 'tarball':
            return True
        for ext in ['.tar.gz', '.tgz', '.tar.bz2', 'tbz2', '.tar.xz', '.tar', '.zip']:
            if self.path.endswith(ext):
                return True
        return False

class PatchApplier(Applier):
    def applyTo(self, target):
        self.runner.command('patch --no-backup-if-mismatch -p1 -d ' + target + ' < ' + self.path, shell=True)
    def isValid(self):
        return self.path.endswith('.patch')    or self.path.endswith('.diff') or self.type == 'patch'

class CopyFileApplier(Applier):
    def __init__(self, runner, config):
        Applier.__init__(self, runner, config)
        self.filepath = config['filepath'] if 'filepath' in config else os.path.basename(config['url'])
    def applyTo(self, target):
        shutil.copyfile(self.path, os.path.join(target, self.filepath))
    def isValid(self):
        return os.path.isfile(self.path)

class GitRepoApplier(Applier):
    def __init__(self, runner, config):
        Applier.__init__(self, runner, config)
        self.url = config['url']
    def applyTo(self, target):
        call = ['git', 'clone', self.url]
        if 'branch' in self.config:
            call += ['-b', self.config['branch']]
        call.append(target)
        self.runner.command(call)
        if 'revision' in self.config:
            wd = os.getcwd()
            os.chdir(target)
            self.runner.command(['git', 'checkout', self.config['revision']])
            os.chdir(wd)
    def isValid(self):
        return self.type == 'git' or 'branch' in self.config or 'commit' in self.config

class DirectoryApplier(Applier):
    def applyTo(self, target):
        self.runner.ensureDir(target)
        self.runner.command(['rsync', '-rlt', self.path+'/', target+'/'])
    def isValid(self):
        return os.path.isdir(self.path)

class Project:
    def __init__(self, runner, config):
        self.runner = runner
        self.config = config
        self.hash = self.hashDict(self.config)
        self.dirname = config['dirname']
        self.symlinks = config['symlinks'] if 'symlinks' in config else None
        self.pipeline = deepcopy(config['build']) if 'build' in config else []
        self.git = False
        self.type = config['type'] if 'type' in config else None
        self.protected = config['protected'] if 'protected' in config else False
    def isValid(self):
        return True
    def build(self, target):
        self.runner.ensureDir(target)
        for config in self.pipeline:
            ressource = Ressource(self.runner, config)
            ressource.download()
            ressource.applyTo(target)
    def hashDict(self, the_dict):
        jsonDump = json.dumps(the_dict, sort_keys=True)
        return hashlib.sha1(jsonDump.encode('utf-8')).hexdigest()
    def convertToMake(self):
        parts = self.dirname.split('-', 2)
        pkey = "projects[%s]" % parts[0];
        pipeline = copy(self.pipeline)
        first = Ressource(self.runner, pipeline.pop(0))
        first.convertToMake(pkey + '[download]')
        for config in pipeline:
            ressource = Ressource(self.runner, config)
            ressource.convertToMake(pkey + '[patch][]', True)
        print()

class DrupalOrgProject(Project):
    def __init__(self, runner, config):
        Project.__init__(self, runner, config)
        parts = self.dirname.split('-', 2)
        if len(parts) == 3:
            self.project, core, self.version = parts
            project_build = {
                'url': 'http://ftp.drupal.org/files/projects/' + self.dirname + '.tar.gz',
            }
            if 'hash' in self.config:
                project_build['hash'] = self.config['hash']
            self.pipeline.insert(0, project_build)
    def isValid(self):
        return self.type == 'drupal.org' and len(self.pipeline) >= 1
    def convertToMake(self):
        pkey = "projects[%s]" % self.project;
        print("%s[version] = %s" % (pkey, self.version))
        pipeline = copy(self.pipeline)
        pipeline.pop(0)
        for config in pipeline:
            ressource = Ressource(self.runner, config)
            ressource.convertToMake(pkey + '[patch][]', True)
        print()

