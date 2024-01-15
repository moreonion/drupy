"""CLI handling and top-level execution."""

import os
import os.path
import shlex
import shutil
import subprocess
import sys
from argparse import ArgumentParser
from glob import glob

from . import objects, resolver
from .targets import DBInstallTarget, ResetCacheTarget, SiteBuildTarget, SiteInstallTarget


class CommandParser(ArgumentParser):
    """Parse the command line arguments."""

    def __init__(self):
        """Create a new parser instance."""
        defaults = {
            "WWWDIR": "/var/www",
            "MOTOOLS": "/var/www/projects/motools",
            "DTREE": "drupal7",
            "DB_PREFIX": None,
            "OPCACHE_RESET_URL": "http://localhost/reset.php?key=",
            "OPCACHE_RESET_KEY": None,
            "DBUILD_OVERRIDES_DIR": os.environ["HOME"] + "/code/drupal",
        }
        for var in defaults:
            if var in os.environ:
                defaults[var] = os.environ[var]

        ArgumentParser.__init__(
            self,
            usage="%(prog)s command [options] sites",
            description="Tools for building json-based drupal receipies.",
        )
        self.add_argument(
            "target",
            metavar="target",
            type=str,
            choices=["build", "install", "db-install", "convert-to-make", "report", "clean"],
            help=(
                "Build target. Possible targets are: "
                "build, install, db-install, convert-to-make, report, clean"
            ),
        )
        self.add_argument(
            "sites",
            metavar="sites",
            type=str,
            nargs="*",
            help=(
                "Sites to build. If no sites are specified the current directory is used to guess "
                "one. Use * to build all sites."
            ),
        )

        output_group = self.add_argument_group("Output options")
        output_group.add_argument(
            "-v",
            "--verbose",
            dest="verbose",
            action="store_true",
            help="Be verbose (default: false)",
            default=False,
        )
        output_group.add_argument(
            "--debug",
            dest="debug",
            action="store_true",
            help="Enable debug output and keep tmp dirs (default: false)",
            default=False,
        )
        output_group.add_argument(
            "-d",
            "--devel",
            dest="devel",
            action="store_true",
            help="Devel mode: keep .git directories and don't modify .info files (default: False)",
            default=False,
        )

        actions_group = self.add_argument_group("Actions")
        actions_group.add_argument(
            "-r",
            "--rebuild",
            dest="rebuild",
            action="store_true",
            help=(
                "Completely rebuild all targets. "
                "(ATTENTION: this may delete uncommitted/pushed work.)"
            ),
        )
        actions_group.add_argument(
            "-u",
            "--update",
            dest="update",
            action="store_true",
            help=(
                "Update targets if possible. "
                "(ATTENTION: this may delete uncommitted/pushed work in contrib folders)"
            ),
        )
        actions_group.add_argument(
            "-n",
            "--dry-run",
            dest="dry_run",
            action="store_true",
            help="Show the list of targets that will be built and exit.",
        )
        actions_group.add_argument(
            "--opcache-reset-url",
            dest="opcache_reset_url",
            type=str,
            default=defaults["OPCACHE_RESET_URL"],
            help="After installing call the following URL to reset caches.",
        )
        actions_group.add_argument(
            "--opcache-reset-key",
            dest="opcache_reset_key",
            type=str,
            default=defaults["OPCACHE_RESET_KEY"],
            help="Append this key to the cache-reset url for authentication.",
        )
        actions_group.add_argument(
            "--override",
            dest="overrides",
            type=str,
            action="append",
            default=[],
            metavar="$project:$path OR $project",
            help=(
                "Redirect all symlinks named $project to $path. Relative paths use "
                "the --overrides-dir as a base. $path defaults to $project."
            ),
        )

        defaults["source-dir"] = defaults["MOTOOLS"] + "/setups/" + defaults["DTREE"]
        defaults["install-dir"] = defaults["WWWDIR"] + "/" + defaults["DTREE"]
        defaults["overrides-dir"] = defaults["DBUILD_OVERRIDES_DIR"]

        build_group = self.add_argument_group("Path options")
        build_group.add_argument(
            "--drush",
            dest="drush",
            type=str,
            help="Drush command to use for installing sites. (default: drush)",
            default="drush",
        )
        build_group.add_argument(
            "--source-dir",
            dest="source_dir",
            type=str,
            help=(
                "Directory with the site configuration (see README for the config format). "
                f"(default: {defaults['source-dir']})"
            ),
            default=defaults["source-dir"],
        )
        build_group.add_argument(
            "--install-dir",
            dest="install_dir",
            type=str,
            help="Directory where the project will be built. (default: "
            + defaults["install-dir"]
            + ")",
            default=defaults["install-dir"],
        )
        build_group.add_argument(
            "--downloads-dir",
            dest="download_dir",
            type=str,
            help=(
                "Directory where downloaded files will be stored."
                "(default: [install-dir]/downloads)"
            ),
            default=None,
        )
        build_group.add_argument(
            "--overrides-dir",
            dest="overrides_dir",
            type=str,
            help="Base-dir used for project overrides. (default: "
            + defaults["overrides-dir"]
            + ")",
            default=defaults["overrides-dir"],
        )
        build_group.add_argument(
            "--db-prefix",
            dest="db_prefix",
            type=str,
            default=defaults["DB_PREFIX"],
            help="Add a table prefix in front of all databases in db-install. (default: None)",
        )

    def parse_args(self, args=None, namespace=None):
        """Parse the arguments."""
        options = ArgumentParser.parse_args(self, args, namespace)
        if not options.download_dir:
            options.download_dir = os.path.join(options.install_dir, "downloads")

        # parse overrides arguments.
        mapping = {}
        for arg in options.overrides:
            parts = arg.split(":", 2)
            path = parts[1] if len(parts) >= 2 else parts[0]
            if not os.path.isabs(path):
                path = os.path.abspath(options.overrides_dir) + "/" + path
            mapping[parts[0]] = path
        options.overrides = mapping
        return options


class Runner:
    """Coordinate the execution of tasks."""

    def __init__(self):
        """Create a new runner."""
        self.options = CommandParser().parse_args()
        self.commands = {
            "build": self.run_build,
            "install": self.run_install,
            "db-install": self.run_db_install,
            "convert-to-make": self.run_make,
            "report": self.run_report,
            "clean": self.run_clean,
        }
        self.downloader_factory = objects.TypedFactory(
            self,
            "Downloader",
            [
                objects.ScmNoopDownloader,
                objects.UrllibDownloader,
                objects.LocalDownloader,
            ],
        )
        self.applier_factory = objects.TypedFactory(
            self,
            "Applier",
            [
                objects.GitRepoApplier,
                objects.PatchApplier,
                objects.TarballExtract,
                objects.CopyFileApplier,
                objects.DirectoryApplier,
            ],
        )
        self.project_factory = objects.TypedFactory(
            self,
            "Project",
            [
                objects.DrupalOrgProject,
                objects.Project,
            ],
        )
        self.core_config = None
        self.config = None

    def get_downloader(self, config):
        """Create a downloader from a config dict."""
        return self.downloader_factory.produce(config)

    def get_applier(self, config):
        """Create an applier from a config dict."""
        return self.applier_factory.produce(config)

    def get_project(self, config):
        """Create a project from a config dict."""
        return self.project_factory.produce(config)

    def ensure_dir(self, d):
        """Create a directory and all its parents."""
        if not os.path.exists(d):
            os.makedirs(d)

    def rsync_dirs(self, source, target, excludes=None, only_non_existing=False):
        """Update the contents of the target directory based on the source directory."""
        self.ensure_dir(target)
        cmd = ["rsync", "-rlt", "--delete", "--progress", source + "/", target + "/"]
        if only_non_existing:
            cmd.append("--ignore-existing")
        cmd += ["--exclude=" + x for x in (excludes or [])]
        self.command(cmd)

    def project_symlinks(self, path, elements, depth=0):
        """Create a directory structure containing symlinks based on a dict."""
        dirqueue = [(path, depth, elements)]
        projects = self.options.projects_dir
        while len(dirqueue) > 0:
            path, depth, element = dirqueue.pop(0)
            if isinstance(element, str):
                if os.path.lexists(path):
                    os.unlink(path)
                target = os.path.join("../" * depth + projects, element)
                name = os.path.basename(path)
                if name in self.options.overrides:
                    target = self.options.overrides[name]
                if self.options.verbose:
                    print(f"symlink: {path} -> {target}")
                os.symlink(target, path)
            else:
                if not os.path.exists(path):
                    os.makedirs(path)
                for name, subelement in element.items():
                    dirqueue.append((path + "/" + name, depth + 1, subelement))

    def drush(self, arguments):
        """Execute a drush command."""
        cmd = shlex.split(self.options.drush)
        self.command(cmd + arguments, shell=False)

    def command(self, cmd, shell=False):
        """Execute a (shell) command."""
        if self.options.verbose:
            print(f"{os.getcwd()} > {cmd} ({shell})")
        if self.options.debug:
            subprocess.check_call(
                cmd, shell=shell, env=os.environ, stderr=sys.stderr, stdout=sys.stdout
            )
        else:
            subprocess.check_call(cmd, shell=shell, env=os.environ)

    def parse_config(self):
        """Read config from a file."""
        o = self.options
        path = glob(o.source_dir + "/project.*")[0]
        self.config = objects.Tree(self, path)
        o.document_root = self.config.config["documentRoot"]
        o.core_config = self.config.config["core"]
        o.projects_dir = self.config.config["projectsDir"]

    def run(self):
        """Execute all actions to build the target."""
        self.parse_config()
        self.commands[self.options.target]()

    def run_build(self):
        """Build all projects for the specified sites."""
        t = [SiteBuildTarget(self, s) for s in self.options.sites]
        r = resolver.Resolver(self.options)
        r.resolve(t)
        r.execute()

    def run_install(self):
        """Build and install all specified sites."""
        r = resolver.Resolver(self.options)
        r.resolve(
            [SiteInstallTarget(self, s) for s in self.options.sites]
            + [ResetCacheTarget(self, self.options.sites)]
        )
        r.execute()

    def run_db_install(self):
        """Build, install and db-install all specified sites."""
        r = resolver.Resolver(self.options)
        r.resolve(
            [DBInstallTarget(self, s) for s in self.options.sites]
            + [ResetCacheTarget(self, self.options.sites)]
        )
        r.execute()

    def run_make(self):
        """Generate a drush makefile from the project.yaml."""
        config = self.config.config
        print("api = 2")
        if config["core"]["project"].startswith("drupal-"):
            print("core = 7.x")
        for project in self.config.projects.values():
            project.convert_to_make()

    def run_report(self):
        """Report about inconsistencies in the current configuration and installation.

        Currently the following things are reported:
        - Obsolete projects: Projects in the projects directory that are not
          currently defined anywhere. Once all sites are up-to-date these
          projects can be safely removed (with the clean command).
        - Unused projects: Projects that are defined but aren't used by any
          site.
        """
        print("Checking projects …")
        tree = self.config
        installed_projects = tree.installed_projects
        defined_projects = tree.defined_projects

        obsolete_projects = installed_projects - defined_projects
        if obsolete_projects:
            print()
            print("Obsolete projects:")
            for p in sorted(obsolete_projects):
                print(f"\t{p}")

        unused_projects = defined_projects - tree.used_projects
        if unused_projects:
            print()
            print("Unused projects:")
            for p in sorted(unused_projects):
                print(f"\t{p}")

    def run_clean(self):
        """Delete all obsolete projects."""
        tree = self.config
        o = self.options

        obsolete_projects = tree.installed_projects - tree.defined_projects
        if obsolete_projects:
            print("Deleting obsolete projects …")
            for p in sorted(obsolete_projects):
                shutil.rmtree(os.path.join(o.install_dir, o.projects_dir, p))
                print(f"\t{p} deleted.")


def main():
    """Entry point for the CLI."""
    Runner().run()
