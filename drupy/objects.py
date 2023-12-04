"""Define objects for interpreting config."""

import abc
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
    """Recursively merge defaults into a config dictionary."""
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
    import ruamel.yaml

    yaml = ruamel.yaml.YAML(typ="safe", pure=True)
    parsers[".yaml"] = yaml.load
except ImportError:
    pass


def get_parser(path):
    """Get a config file parser based on the file extension."""
    _, ext = os.path.splitext(path)
    return parsers[ext]


class Config:
    """Top-level config object."""

    defaults = {}

    def __init__(self, runner, path):
        """Create a new instance."""
        self.runner = runner
        self.path = path
        self.config = self.read_config()

    def read_config(self):
        """Read the config, fetch referenced remote config and add defaults."""
        o = self.runner.options
        files = [(None, self.path)]
        data = collections.OrderedDict()
        while len(files) > 0:
            rel_to, path = files.pop(0)
            path = (
                self.runner.get_downloader({"url": path})
                .download(rel_to, o.download_dir)
                .localpath()
            )
            new_data = self.read_file(path)
            if "includes" in new_data:
                includes = new_data["includes"]
                del new_data["includes"]
                rel_to = os.path.dirname(path)
                for inc in includes:
                    files.append((rel_to, inc))
            add_defaults(data, new_data)
        add_defaults(data, self.defaults)
        return data

    def read_file(self, path):
        """Read config from a file."""
        parser = get_parser(path)
        with open(path, encoding="utf-8") as configfile:
            try:
                return parser(configfile)
            except ValueError as exc:
                raise ValueError(f"Error while parsing {path}: {exc}") from exc


class Tree(Config):
    """Config for one Drupal root."""

    defaults = {
        "documentRoot": "htdocs",
        "projectsDir": "projects",
        "downloadDir": "downloads",
        "core": {"project": None, "profiles": {}, "protected": []},
        "projects": {},
    }

    def __init__(self, runner, path):
        """Create a new tree instance."""
        Config.__init__(self, runner, path)
        self.projects = collections.OrderedDict()
        for dirname, config in self.config["projects"].items():
            config["dirname"] = dirname
            self.projects[dirname] = runner.get_project(config)

        self.sites = {}
        for configpath in glob(os.path.dirname(path) + "/*.site.*"):
            basename = os.path.basename(configpath)
            site = basename[: basename.find(".")]
            if "." not in site:
                self.sites[site] = Site(self.runner, site, configpath)

    @property
    def defined_projects(self):
        """Get a list of all the projects defined in the config."""
        return frozenset(self.projects.keys())

    @property
    def installed_projects(self):
        """Get a set of all the installed projects."""
        o = self.runner.options
        return frozenset(os.listdir(os.path.join(o.install_dir, o.projects_dir)))

    @property
    def used_projects(self):
        """Generate a set of all the projects used in this tree."""
        used_projects = set()
        for s in self.sites.values():
            used_projects.update(s.projects())
        used_projects.add(self.config["core"]["project"])
        return used_projects


class Site(Config):
    """Config representing one site in a Drupal multi-site setup."""

    defaults = {
        "profile": "standard",
        "db-url": None,
        "site-mail": None,
        "site-name": None,
        "account-mail": None,
        "links": {},
    }

    def __init__(self, runner, name, path):
        """Create a new site."""
        Config.__init__(self, runner, path)
        self.site = name
        if not self.config["db-url"]:
            self.config["db-url"] = "dpl:dplpw@localhost/" + name

    def project_from_symlink_path(self, path):
        """Calculate the project name from the referenced path."""
        project = path
        # The symlink might point to a sub-directory of the project.
        if "/" in project:
            project = project[: project.find("/")]
        return project

    def projects(self):
        """Iterate through all the referenced projects."""
        queue = [self.config["links"]]
        while queue:
            d = queue.pop(0)
            for project_or_dir in d.values():
                if isinstance(project_or_dir, dict):
                    queue.append(project_or_dir)
                else:
                    yield self.project_from_symlink_path(project_or_dir)

        profile = self.profile()
        if profile:
            path = self.runner.config.config["core"]["profiles"][profile]
            yield self.project_from_symlink_path(path)

    def profile(self):
        """Return the name of the custom profile used for this site (if any)."""
        profile = self.config["profile"]
        if profile not in ("minimal", "standard", "testing"):
            return profile
        return None


class TypedFactory:
    """Factory for config based objects."""

    # pylint: disable=too-few-public-methods

    def __init__(self, runner, name, types):
        """Create a new factory instance."""
        self.runner, self.name, self.types = runner, name, types

    def produce(self, config):
        """Instantiate the object matching the passed config."""
        for type_ in self.types:
            try:
                obj = type_(self.runner, config)
                if obj.is_valid():
                    return obj
            except ValueError as exc:
                # Implementations can err out of non-applicable configs.
                if self.runner.options.verbose:
                    print(f"Not a {type.__name__}: {exc}")
        # pylint: disable=broad-exception-raised
        raise Exception(f"No matching {self.name} for input: {config}")


class Downloader(abc.ABC):
    """Common interface for local files, remote ressorces and SCM repos."""

    def __init__(self, runner, config):
        """Create a new downloader."""
        self.runner = runner
        self.url = config["url"]
        self.hash = None
        if self.url.find("#") != -1:
            self.url, self.hash = self.url.split("#", 1)
        self.scheme = urllib.parse.urlparse(self.url).scheme

    def download(self, _rel_to, _store):
        """Fetch the ressource if needed."""
        return self

    def localpath(self):
        """Get the local path of the file."""
        return self.url

    def is_valid(self):
        """Check if the config is valid for this type of downloader."""
        return True

    def convert_to_make(self, pfx, patch_short_hand=False):
        """Print the drush makefile definitions representing this downloader."""
        if patch_short_hand:
            print(f"{pfx} = {self.url}")
        else:
            print(f"{pfx}[type] = file" % (pfx))
            print(f"{pfx}[url] = {self.url}")


class ScmNoopDownloader(Downloader):
    """Represent SCM repositories as downloadable ressources."""

    def __init__(self, runner, config):
        """Create a new SCM downloader."""
        has_scm_type = "type" in config and config["type"] in ["git"]
        has_revision_or_branch = "revision" in config or "branch" in config
        if not has_scm_type and not has_revision_or_branch:
            raise ValueError("This is not a SCM ressource")
        Downloader.__init__(self, runner, config)
        self.scm_type = "git"
        self.branch = config["branch"] if "branch" in config else False
        self.revision = config["revision"] if "revision" in config else False

    def convert_to_make(self, pfx, patch_short_hand=False):
        """Print the drush makefile definitions representing this downloader."""
        print(pfx + "[type] = " + self.scm_type)
        print(pfx + "[url] = " + self.url)
        if self.branch:
            print(pfx + "[branch] = " + self.branch)
        if self.revision:
            print(pfx + "[revision] = " + self.revision)


class LocalDownloader(Downloader):
    """Represent a local file using the Downloader interface."""

    def __init__(self, runner, config):
        """Create a new downloader."""
        super().__init__(runner, config)
        self.path = None

    def download(self, rel_to, _store):
        """Set the path for a local file."""
        if not rel_to or os.path.isabs(self.url):
            self.path = self.url
        else:
            self.path = os.path.join(rel_to, self.url)
        return self

    def localpath(self):
        """Get the local path of the file."""
        return self.path

    def is_valid(self):
        """Check if the config is valid for this type of downloader."""
        return not self.scheme


class UrllibDownloader(Downloader):
    """Download a file from a remote URL."""

    def __init__(self, runner, config):
        """Create a new downloader."""
        super().__init__(runner, config)
        self.path = None

    def download(self, _rel_to, store):
        """Download the file from the remote URL."""
        # pylint: disable=broad-exception-raised
        filename = self.url.replace("/", "-").replace(":", "-")
        self.path = os.path.join(store, filename)
        if os.path.exists(self.path):
            if not self.hash or self.get_hash() == self.hash:
                return self
            os.unlink(self.path)
        if self.runner.options.verbose:
            print(f"Downloading {self.url}")
        try:
            with open(self.path, "wb") as target, urllib.request.urlopen(self.url) as f:
                target.write(f.read())
        except urllib.error.HTTPError as exc:
            msg = "Error during download of {}: {}"
            raise Exception(msg.format(self.url, str(exc))) from exc
        if self.hash:
            actual_hash = self.get_hash()
            if self.hash != actual_hash:
                msg = "Hash of file downloaded from {} wrong: {} instead of {}"
                raise Exception(msg.format(self.url, actual_hash, self.hash))
        return self

    def get_hash(self):
        """Calculate the hash of the downloaded file."""
        with open(self.path, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()

    def localpath(self):
        """Get the local path of the downloaded file."""
        return self.path

    def is_valid(self):
        """Check if the config is valid for this type of downloader."""
        schemes = ["http", "https", "ftp"]
        return self.scheme in schemes and not self.url.endswith(".git")


class Ressource:
    """Downloadable resource."""

    def __init__(self, runner, config):
        """Create a new resource."""
        self.runner = runner
        self.config = deepcopy(config)
        if isinstance(self.config, str):
            self.config = {"url": config}
        add_defaults(self.config, {"devel": None})

    def download(self):
        """Download the ressource into the download folder."""
        o = self.runner.options
        downloader = self.runner.get_downloader(self.config)
        downloader.download(o.source_dir, o.download_dir)
        self.config["localpath"] = downloader.localpath()

    def apply_to(self, target):
        """Extract or copy the downloaded resource into a folder."""
        devel = self.config["devel"]
        if devel is not None and devel != self.runner.options.devel:
            # Don't apply ressources that are production or devel only
            return
        applier = self.runner.get_applier(self.config)
        applier.apply_to(target)

    def convert_to_make(self, pfx, patch_short_hand=False):
        """Print the drush makefile definitions representing this ressource."""
        if "purpose" in self.config:
            comment = "; " + self.config["purpose"]
            if "link" in self.config:
                comment += " - " + self.config["link"]
            print(comment)
        downloader = self.runner.get_downloader(self.config)
        downloader.convert_to_make(pfx, patch_short_hand)


class Applier(abc.ABC):
    """Applier classes represent modifications to a target folder."""

    def __init__(self, runner, config):
        """Set the default properties."""
        self.runner = runner
        self.path = config["localpath"]
        self.type = config["type"] if "type" in config else None
        self.config = config

    @abc.abstractmethod
    def apply_to(self, target):
        """Apply the actions to the target directory."""

    @abc.abstractmethod
    def is_valid(self):
        """Check if the config is valid for this type of applier."""


class TarballExtract(Applier):
    """Extract a tarball."""

    exts = [".tar.gz", ".tgz", ".tar.bz2", "tbz2", ".tar.xz", ".tar", ".zip"]

    def apply_to(self, target):
        """Apply the changes to the target directory."""
        unpack = setuptools.archive_util.unpack_archive

        # Dry run to find longest prefix.
        paths = []

        def record_paths(name, _):
            paths.append(name)
            return False

        unpack(self.path, target, progress_filter=record_paths)
        prefix = len(os.path.commonprefix(paths))

        # Actuall unpacking.
        def extract_filter(name, _):
            if len(name) <= prefix:
                return False
            name = name[prefix:]
            if name.startswith("/"):
                name = name[1:]
            return target + "/" + name

        unpack(self.path, target, progress_filter=extract_filter)
        utils.normalize_permissions(target)

    def is_valid(self):
        """Check if the config is valid for this type of applier."""
        if self.type == "tarball":
            return True
        for ext in self.exts:
            if self.path.endswith(ext):
                return True
        return False


class PatchApplier(Applier):
    """Apply a patch."""

    def apply_to(self, target):
        """Apply the changes to the target directory."""
        cmd = "patch --no-backup-if-mismatch -p1 -d {} < {}"
        self.runner.command(cmd.format(target, self.path), shell=True)

    def is_valid(self):
        """Check if the config is valid for this type of applier."""
        p = self.path
        return p.endswith(".patch") or p.endswith(".diff") or self.type == "patch"


class CopyFileApplier(Applier):
    """Copy a file to the target directory."""

    def __init__(self, runner, config):
        """Create a new file adapter."""
        Applier.__init__(self, runner, config)
        add_defaults(config, {"filepath": os.path.basename(config["url"])})
        self.filepath = config["filepath"]

    def apply_to(self, target):
        """Apply the changes to the target directory."""
        shutil.copyfile(self.path, os.path.join(target, self.filepath))

    def is_valid(self):
        """Check if the config is valid for this type of applier."""
        return os.path.isfile(self.path)


class GitRepoApplier(Applier):
    """Cone a git repositiory."""

    def __init__(self, runner, config):
        """Create a new git repo adapter."""
        Applier.__init__(self, runner, config)
        self.url = config["url"]
        self.shallow = config.get("shallow", True)

    def apply_to(self, target):
        """Apply the changes to the target directory."""
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
        """Check if the config is valid for this type of applier."""
        return self.type == "git" or "branch" in self.config or "revision" in self.config


class DirectoryApplier(Applier):
    """Copy the content of one directory into the target directory."""

    def apply_to(self, target):
        """Apply the changes to the target directory."""
        self.runner.ensure_dir(target)
        self.runner.command(["rsync", "-rlt", self.path + "/", target + "/"])

    def is_valid(self):
        """Check if the project config is valid for its type."""
        return os.path.isdir(self.path)


class Project:
    """Project base class."""

    def __init__(self, runner, config):
        """Create a new project."""
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
        self.hash = self.hash_dict(self.config)
        self.dirname = config["dirname"]
        self.pipeline = deepcopy(config["build"])
        self.type = config["type"]
        self.protected = config["protected"]

    def is_valid(self):
        """Check if the project config is valid for its type."""
        return True

    def build(self, target):
        """Download and extract the project."""
        self.runner.ensure_dir(target)
        for config in self.pipeline:
            ressource = Ressource(self.runner, config)
            ressource.download()
            ressource.apply_to(target)

    def hash_dict(self, the_dict):
        """Generate a unique hash for this project configuration."""
        json_dump = json.dumps(the_dict, sort_keys=True)
        return hashlib.sha1(json_dump.encode("utf-8")).hexdigest()

    def convert_to_make(self):
        """Print drush makefile lines for this project."""
        parts = self.dirname.split("-", 2)
        pkey = f"projects[{parts[0]}]"
        pipeline = copy(self.pipeline)
        first = Ressource(self.runner, pipeline.pop(0))
        first.convert_to_make(pkey + "[download]")
        for config in pipeline:
            ressource = Ressource(self.runner, config)
            ressource.convert_to_make(pkey + "[patch][]", True)
        print()


class DrupalOrgProject(Project):
    """Project representing a project published on drupal.org."""

    package_pattern = re.compile(
        "([a-z0-9_]+)-(\\d+\\.x)-(\\d+\\.x-dev|\\d+\\.\\d+(-(alpha|beta|rc)\\d+)?)"
    )
    url_pattern = "https://ftp.drupal.org/files/projects/{}-{}-{}.tar.gz"

    def __init__(self, runner, config):
        """Split the dirname to see if this is a valid drupal.org package spec.

        - Automatically prepends downloading the drupal.org package to the build
          queue.
        - Packages with a valid spect are detected as drupal.org packages even
          if they don't declare config['type'] = 'drupal.org' explicitly.
        """
        Project.__init__(self, runner, config)
        try:
            self.project, self.core, self.version, self.patches = self.split_project(self.dirname)
            # Prepend drupal.org package download if there is not already
            # another non-patch build item in the pipeline.
            if not self.pipeline or self.is_patch(self.pipeline[0]):
                build = {"url": self.url_pattern.format(self.project, self.core, self.version)}
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
        """Split a directory name into project, core-version, version and patches.

        Patches should be separated from the main project string and one another
        using a '+'.
        """
        p = name.split("+")
        name, extras = p[0], tuple(p[1:])
        match = cls.package_pattern.fullmatch(name)
        if match:
            return match.group(1), match.group(2), match.group(3), extras
        raise ValueError(f'Not a valid package string: "{name}"')

    def is_valid(self):
        """Check if the project config is valid for its type."""
        return self.type == "drupal.org" and len(self.pipeline) >= 1

    def convert_to_make(self):
        """Print drush makefile lines for this project."""
        pkey = f"projects[{self.project}]"
        print(f"{pkey}[version] = {self.version}")
        pipeline = copy(self.pipeline)
        pipeline.pop(0)
        for config in pipeline:
            ressource = Ressource(self.runner, config)
            ressource.convert_to_make(pkey + "[patch][]", True)
        print()
