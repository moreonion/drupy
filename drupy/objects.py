import collections
import hashlib
import json
import os.path
import re
import shutil
import urllib.parse
import urllib.request
from copy import copy, deepcopy
from functools import partial
from glob import glob

import setuptools.archive_util

from drupy import utils


def add_defaults(config, defaults):
    queue = [(config, defaults)]

    while len(queue) > 0:
        c, d = queue.pop(0)
        for k in d.keys():
            if k in c:
                if isinstance(c[k], dict) and isinstance(d[k], dict):
                    queue.append((c[k], d[k]))
            else:
                c[k] = deepcopy(d[k])


parsers = {".json": partial(json.load, object_pairs_hook=collections.OrderedDict)}

# Optionally load support for yaml config files.
try:
    from ruamel import yaml

    parsers[".yaml"] = partial(yaml.load, Loader=yaml.RoundTripLoader)
except ImportError:
    pass


def get_parser(path):
    _, ext = os.path.splitext(path)
    return parsers[ext]


class Config:
    defaults = {}

    def __init__(self, runner, path):
        self.runner = runner
        self.path = path
        self.config = self.read_config()

    def read_config(self):
        o = self.runner.options
        files = [(None, self.path)]
        data = collections.OrderedDict()
        while len(files) > 0:
            relTo, path = files.pop(0)
            path = (
                self.runner.get_downloader({"url": path})
                .download(relTo, o.download_dir)
                .localpath()
            )
            new_data = self.read_file(path)
            if "includes" in new_data:
                includes = new_data["includes"]
                del new_data["includes"]
                relTo = os.path.dirname(path)
                for inc in includes:
                    files.append((relTo, inc))
            add_defaults(data, new_data)
        add_defaults(data, self.defaults)
        return data

    def read_file(self, path):
        parser = get_parser(path)
        with open(path) as configfile:
            try:
                return parser(configfile)
            except ValueError as e:
                raise ValueError("Error while parsing %s: %s" % (path, str(e)))


class Tree(Config):
    defaults = {
        "documentRoot": "htdocs",
        "projectsDir": "projects",
        "downloadDir": "downloads",
        "core": {"project": None, "profiles": {}, "protected": []},
        "projects": {},
    }

    def __init__(self, runner, path):
        Config.__init__(self, runner, path)
        self.projects = collections.OrderedDict()
        for dirname, config in self.config["projects"].items():
            config["dirname"] = dirname
            self.projects[dirname] = runner.getProject(config)

        self.sites = {}
        for configpath in glob(os.path.dirname(path) + "/*.site.*"):
            basename = os.path.basename(configpath)
            site = basename[: basename.find(".")]
            if "." not in site:
                self.sites[site] = Site(self.runner, site, configpath)

    @property
    def defined_projects(self):
        return frozenset(self.projects.keys())

    @property
    def installed_projects(self):
        o = self.runner.options
        return frozenset(os.listdir(os.path.join(o.install_dir, o.projects_dir)))

    @property
    def used_projects(self):
        used_projects = set()
        for s in self.sites.values():
            used_projects.update(s.projects())
        used_projects.add(self.config["core"]["project"])
        return used_projects


class Site(Config):
    defaults = {
        "profile": "standard",
        "db-url": None,
        "site-mail": None,
        "site-name": None,
        "account-mail": None,
        "links": {},
    }

    def __init__(self, runner, name, path):
        Config.__init__(self, runner, path)
        self.site = name
        if not self.config["db-url"]:
            self.config["db-url"] = "dpl:dplpw@localhost/" + name

    def project_from_symlink_path(self, path):
        project = path
        # The symlink might point to a sub-directory of the project.
        if "/" in project:
            project = project[: project.find("/")]
        return project

    def projects(self):
        q = [self.config["links"]]
        while q:
            d = q.pop(0)
            for alias, project_or_dir in d.items():
                if isinstance(project_or_dir, dict):
                    q.append(project_or_dir)
                else:
                    yield self.project_from_symlink_path(project_or_dir)

        profile = self.profile()
        if profile:
            path = self.runner.config.config["core"]["profiles"][profile]
            yield self.project_from_symlink_path(path)

    def profile(self):
        profile = self.config["profile"]
        if profile not in ("minimal", "standard", "testing"):
            return profile


class TypedFactory:
    def __init__(self, runner, name, types):
        self.runner, self.name, self.types = runner, name, types

    def produce(self, config):
        for t in self.types:
            try:
                obj = t(self.runner, config)
                if obj.is_valid():
                    return obj
            except ValueError as e:
                """Implementations can err out of non-applicable configs."""
                if self.runner.options.verbose:
                    print("Not a %s: %s" % (t.__name__, e))
        raise Exception("No matching %s for input: %s" % (self.name, config))


class Downloader:
    def __init__(self, runner, config):
        self.runner = runner
        self.url = config["url"]
        self.hash = None
        if self.url.find("#") != -1:
            self.url, self.hash = self.url.split("#", 1)
        self.scheme = urllib.parse.urlparse(self.url).scheme

    def download(self, relTo, store):
        return self

    def localpath(self):
        return self.url

    def is_valid(self):
        return True

    def convert_to_make(self, pfx, patch_short_hand=False):
        if patch_short_hand:
            print("%s = %s" % (pfx, self.url))
        else:
            print("%s[type] = file" % (pfx))
            print("%s[url] = %s" % (pfx, self.url))


class ScmNoopDownloader(Downloader):
    def __init__(self, runner, config):
        has_scm_type = "type" in config and config["type"] in ["git"]
        has_revision_or_branch = "revision" in config or "branch" in config
        if not has_scm_type and not has_revision_or_branch:
            raise ValueError("This is not a SCM ressource")
        Downloader.__init__(self, runner, config)
        self.scm_type = "git"
        self.branch = config["branch"] if "branch" in config else False
        self.revision = config["revision"] if "revision" in config else False

    def convert_to_make(self, pfx, patch_short_hand=False):
        print(pfx + "[type] = " + self.scm_type)
        print(pfx + "[url] = " + self.url)
        if self.branch:
            print(pfx + "[branch] = " + self.branch)
        if self.revision:
            print(pfx + "[revision] = " + self.revision)


class LocalDownloader(Downloader):
    def download(self, relTo, store):
        if not relTo or os.path.isabs(self.url):
            self.path = self.url
        else:
            self.path = os.path.join(relTo, self.url)
        return self

    def localpath(self):
        return self.path

    def is_valid(self):
        return not self.scheme


class UrllibDownloader(Downloader):
    def __init__(self, runner, config):
        Downloader.__init__(self, runner, config)

    def download(self, relTo, store):
        filename = self.url.replace("/", "-").replace(":", "-")
        self.path = os.path.join(store, filename)
        if os.path.exists(self.path):
            if not self.hash or self.get_hash() == self.hash:
                return
            else:
                os.unlink(self.path)
        if self.runner.options.verbose:
            print("Downloading %s" % self.url)
        try:
            f = urllib.request.urlopen(self.url)
        except urllib.error.HTTPError as e:
            msg = "Error during download of {}: {}"
            raise Exception(msg.format(self.url, str(e)))
        with open(self.path, "wb") as target:
            target.write(f.read())
        if self.hash:
            actual_hash = self.get_hash()
            if self.hash != actual_hash:
                msg = "Hash of file downloaded from {} wrong: {} instead of {}"
                raise Exception(msg.format(self.url, actual_hash, self.hash))
        return self

    def get_hash(self):
        with open(self.path, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()

    def localpath(self):
        return self.path

    def is_valid(self):
        schemes = ["http", "https", "ftp"]
        return self.scheme in schemes and not self.url.endswith(".git")


class Ressource:
    def __init__(self, runner, config):
        self.runner = runner
        self.config = deepcopy(config)
        if type(self.config) is str:
            self.config = {"url": config}
        add_defaults(self.config, dict(devel=None))

    def download(self):
        o = self.runner.options
        downloader = self.runner.get_downloader(self.config)
        downloader.download(o.source_dir, o.download_dir)
        self.config["localpath"] = downloader.localpath()

    def apply_to(self, target):
        devel = self.config["devel"]
        if devel is not None and devel != self.runner.options.devel:
            "Don't apply ressources that are production or devel only"
            return
        applier = self.runner.get_applier(self.config)
        applier.apply_to(target)

    def convert_to_make(self, pfx, patch_short_hand=False):
        if "purpose" in self.config:
            comment = "; " + self.config["purpose"]
            if "link" in self.config:
                comment += " - " + self.config["link"]
            print(comment)
        downloader = self.runner.get_downloader(self.config)
        downloader.convert_to_make(pfx, patch_short_hand)


class Applier:
    def __init__(self, runner, config):
        self.runner = runner
        self.path = config["localpath"]
        self.type = config["type"] if "type" in config else None
        self.config = config


class TarballExtract(Applier):
    exts = [".tar.gz", ".tgz", ".tar.bz2", "tbz2", ".tar.xz", ".tar", ".zip"]

    def apply_to(self, target):
        unpack = setuptools.archive_util.unpack_archive

        # Dry run to find longest prefix.
        paths = []

        def record_paths(name, destination):
            paths.append(name)
            return False

        unpack(self.path, target, progress_filter=record_paths)
        prefix = len(os.path.commonprefix(paths))

        # Actuall unpacking.
        def extract_filter(name, destination):
            if len(name) <= prefix:
                return False
            name = name[prefix:]
            if name.startswith("/"):
                name = name[1:]
            return target + "/" + name

        unpack(self.path, target, progress_filter=extract_filter)
        utils.normalize_permissions(target)

    def is_valid(self):
        if self.type == "tarball":
            return True
        for ext in self.exts:
            if self.path.endswith(ext):
                return True
        return False


class PatchApplier(Applier):
    def apply_to(self, target):
        cmd = "patch --no-backup-if-mismatch -p1 -d {} < {}"
        self.runner.command(cmd.format(target, self.path), shell=True)

    def is_valid(self):
        p = self.path
        return p.endswith(".patch") or p.endswith(".diff") or self.type == "patch"


class CopyFileApplier(Applier):
    def __init__(self, runner, config):
        Applier.__init__(self, runner, config)
        add_defaults(config, dict(filepath=os.path.basename(config["url"])))
        self.filepath = config["filepath"]

    def apply_to(self, target):
        shutil.copyfile(self.path, os.path.join(target, self.filepath))

    def is_valid(self):
        return os.path.isfile(self.path)


class GitRepoApplier(Applier):
    def __init__(self, runner, config):
        Applier.__init__(self, runner, config)
        self.url = config["url"]
        self.shallow = config.get("shallow", True)

    def apply_to(self, target):
        call = ["git", "clone", self.url]

        if "branch" in self.config:
            call += ["-b", self.config["branch"]]

        has_revision = "revision" in self.config and self.config["revision"]
        if self.shallow and not has_revision:
            call += ["--depth", "1"]

        call.append(target)
        self.runner.command(call)

        if has_revision:
            wd = os.getcwd()
            os.chdir(target)
            self.runner.command(["git", "checkout", self.config["revision"]])
            os.chdir(wd)

    def is_valid(self):
        return self.type == "git" or "branch" in self.config or "revision" in self.config


class DirectoryApplier(Applier):
    def apply_to(self, target):
        self.runner.ensure_dir(target)
        self.runner.command(["rsync", "-rlt", self.path + "/", target + "/"])

    def is_valid(self):
        return os.path.isdir(self.path)


class Project:
    def __init__(self, runner, config):
        add_defaults(
            config,
            {
                "type": None,
                "symlinks": None,
                "build": [],
                "protected": False,
            },
        )
        self.runner = runner
        self.config = config
        self.hash = self.hashDict(self.config)
        self.dirname = config["dirname"]
        self.pipeline = deepcopy(config["build"])
        self.git = False
        self.type = config["type"]
        self.protected = config["protected"]

    def is_valid(self):
        return True

    def build(self, target):
        self.runner.ensure_dir(target)
        for config in self.pipeline:
            ressource = Ressource(self.runner, config)
            ressource.download()
            ressource.apply_to(target)

    def hashDict(self, the_dict):
        jsonDump = json.dumps(the_dict, sort_keys=True)
        return hashlib.sha1(jsonDump.encode("utf-8")).hexdigest()

    def convert_to_make(self):
        parts = self.dirname.split("-", 2)
        pkey = "projects[%s]" % parts[0]
        pipeline = copy(self.pipeline)
        first = Ressource(self.runner, pipeline.pop(0))
        first.convert_to_make(pkey + "[download]")
        for config in pipeline:
            ressource = Ressource(self.runner, config)
            ressource.convert_to_make(pkey + "[patch][]", True)
        print()


class DrupalOrgProject(Project):
    package_pattern = re.compile(
        "([a-z0-9_]+)-(\\d+\\.x)-(\\d+\\.x-dev|\\d+\\.\\d+(-(alpha|beta|rc)\d+)?)"
    )
    url_pattern = "https://ftp.drupal.org/files/projects/{}-{}-{}.tar.gz"

    def __init__(self, runner, config):
        """
        Split dirname to see if this is a valid drupal.org package spec.

        - Automatically prepends downloading the drupal.org package to the build
          queue.
        - Packages with a valid spect are detected as drupal.org packages even
          if they don't declare config['type'] = 'drupal.org' explicitly.
        """
        Project.__init__(self, runner, config)
        try:
            project, core, version, patches = self.split_project(self.dirname)
            # Prepend drupal.org package download if there is not already
            # another non-patch build item in the pipeline.
            if not self.pipeline or self.is_patch(self.pipeline[0]):
                build = dict(url=self.url_pattern.format(project, core, version))
                if "hash" in self.config:
                    build["hash"] = self.config["hash"]
                self.pipeline.insert(0, build)
            if self.type is None:
                self.type = "drupal.org"
        except ValueError:
            pass

    def is_patch(self, config):
        """Check whether pipeline items resolves to a patch."""
        ressource = Ressource(self.runner, config)
        u = ressource.config["url"]
        return (
            u.endswith(".diff") or u.endswith(".patch") or ressource.config.get("type") == "patch"
        )

    @classmethod
    def split_project(cls, name):
        """
        Split a directory name into project, core-version, version and patches.

        Patches should be separated from the main project string and one another
        using a '+'.
        """
        p = name.split("+")
        name, extras = p[0], tuple(p[1:])
        match = cls.package_pattern.fullmatch(name)
        if match:
            return match.group(1), match.group(2), match.group(3), extras
        raise ValueError('Not a valid package string: "{}"'.format(name))

    def is_valid(self):
        return self.type == "drupal.org" and len(self.pipeline) >= 1

    def convert_to_make(self):
        pkey = "projects[%s]" % self.project
        print("%s[version] = %s" % (pkey, self.version))
        pipeline = copy(self.pipeline)
        pipeline.pop(0)
        for config in pipeline:
            ressource = Ressource(self.runner, config)
            ressource.convert_to_make(pkey + "[patch][]", True)
        print()
