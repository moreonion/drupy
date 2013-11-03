#!/usr/bin/env python3
from argparse import ArgumentParser, SUPPRESS
import os, os.path
import subprocess
import sys

from dbuild import resolver, targets, objects

class CommandParser(ArgumentParser):
	def __init__(self):
		ArgumentParser.__init__(self, usage='%(prog)s command [options] sites', description='Tools for building pyddeploy drupal receipies.')
		self.add_argument('target', metavar='target', type=str, choices=['build', 'install', 'db-install'], help='Build target. Possible targets are: build, install, db-install')
		self.add_argument('sites', metavar='sites', type=str, nargs='*', help='Sites to build. If no sites are specified the current directory is used to guess one. Use * to build all sites.')
		
		output_group = self.add_argument_group('Output options')
		output_group.add_argument('-v', '--verbose', dest='verbose', action='store_true', help='Be verbose (default: false)', default=False)
		output_group.add_argument('--debug', dest='debug', action='store_true', help='Enable debug output and keep tmp dirs (default: false)', default=False)
		output_group.add_argument('-d', '--devel', dest='devel', action='store_true', help='Devel mode: keep .git directories and don\'t modify .info files (default: False)', default=False)

		actions_group= self.add_argument_group('Actions')
		actions_group.add_argument('-r', '--rebuild', dest='rebuild', action='store_true', help='Completely rebuild all targets. (ATTENTION: this may delete uncommitted/pushed work.)')
		actions_group.add_argument('-u', '--update', dest='update', action='store_true', help='Update targets if possible. (ATTENTION: this may delete uncommitted/pushed work in contrib folders)')
		actions_group.add_argument('-n', '--dry-run', dest='dry_run', action='store_true', help='Show the list of targets that will be built and exit.')
		
		defaults = {
			'WWWDIR' : '/var/www',
			'MOTOOLS' : '/var/www/projects/motools',
			'DTREE' : 'drupal7',
			'DB_PREFIX' : None,
		}
		for var in defaults:
			if var in os.environ:
				defaults[var] = os.environ[var]
		
		defaults['source-dir']   = defaults['MOTOOLS'] + '/setups/' + defaults['DTREE']
		defaults['install-dir']  = defaults['WWWDIR'] + '/' + defaults['DTREE']
		
		build_group = self.add_argument_group('Path options')
		build_group.add_argument('--source-dir', dest='sourceDir', type=str, help='Directory with the site configuration (see README for the config format). (default: ' + defaults['source-dir'] + ')', default=defaults['source-dir'])
		build_group.add_argument('--install-dir', dest='installDir', type=str, help='Directory where the project will be built. (default: ' + defaults['install-dir'] + ')', default=defaults['install-dir'])
		build_group.add_argument('--downloads-dir', dest='downloadDir', type=str, help='Directory where downloaded files will be stored. (default: [install-dir]/downloads)', default=None)
		build_group.add_argument('--db-prefix', dest='db_prefix', type=str, default=defaults['DB_PREFIX'], help='Add a table prefix in front of all databases in db-install. (default: None)')
	
	def parse_args(self):
		options = ArgumentParser.parse_args(self)
		if not options.downloadDir:
			options.downloadDir = os.path.join(options.installDir, 'downloads')
		return options
		
class Runner:
	def __init__(self):
		self.options = CommandParser().parse_args()
		self.commands = {'build': self.runBuild, 'install': self.runInstall, 'db-install': self.runDBInstall}
		self.downloaderFactory = objects.TypedFactory(self, 'Downloader', [
			objects.ScmNoopDownloader,
			objects.UrllibDownloader,
			objects.LocalDownloader,
		])
		self.applierFactory = objects.TypedFactory(self, 'Applier', [
			objects.GitRepoApplier,
			objects.PatchApplier,
			objects.TarballExtract,
			objects.CopyFileApplier,
			objects.DirectoryApplier,
		])
		self.projectFactory = objects.TypedFactory(self, 'Project', [
			objects.DrupalOrgProject,
			objects.Project,
		])
	
	def getDownloader(self, config):
		return self.downloaderFactory.produce(config)
	
	def getApplier(self, config):
		return self.applierFactory.produce(config)
	
	def getProject(self, config):
		return self.projectFactory.produce(config)
	
	def ensureDir(self, d):
		if not os.path.exists(d):
			os.makedirs(d)
	
	def rsyncDirs(self, source, target, excludes = [], onlyNonExisting=False):
		self.ensureDir(target)
		cmd = ['rsync', '-rlt', '--delete', '--progress', source+'/', target+'/']
		if onlyNonExisting:
			cmd.append('--ignore-existing')
		cmd += ['--exclude=' + x for x in excludes]
		self.command(cmd)
	
	def projectSymlinks(self, path, elements, depth=0):
		dirqueue = [(path, depth, elements)]
		while (len(dirqueue) > 0):
			path, depth, element = dirqueue.pop(0)
			if type(element) is dict:
				if not os.path.exists(path):
					os.makedirs(path)
				for name, subelement in element.items():
					dirqueue.append((path + '/' + name, depth+1, subelement))
			else:
				if os.path.lexists(path):
					os.unlink(path)
				target = os.path.join('../' * depth + self.options.projectsDir, element)
				if self.options.verbose:
					print("symlink: %s -> %s" % (path, target))
				os.symlink(target, path)
	
	def command(self, cmd, shell=False):
		if self.options.verbose:
			print('%s > %s (%s)' % (os.getcwd(), cmd, shell))
		if self.options.debug:
			subprocess.check_call(cmd, shell=shell, env=os.environ, stderr=sys.stderr, stdout=sys.stdout)
		else:
			subprocess.check_call(cmd, shell=shell, env=os.environ)
		
	
	def parseConfig(self):
		o = self.options
		self.config = objects.Tree(self, os.path.join(o.sourceDir, 'project.json'))
		o.documentRoot = self.config.config['documentRoot']
		o.coreConfig = self.config.config['core']
		o.projectsDir = self.config.config['projectsDir']

	
	def run(self):
		self.parseConfig()
		self.commands[self.options.target]()
	
	def runBuild(self):
		t = [targets.BuildAllProjectsTarget(self)]
		r = resolver.Resolver(self.options)
		r.resolve(t)
		r.execute()
	
	def runInstall(self):
		r = resolver.Resolver(self.options)
		r.resolve([targets.SiteInstallTarget(self, site) for site in self.options.sites])
		r.execute()
	
	def runDBInstall(self):
		r = resolver.Resolver(self.options)
		r.resolve([targets.DBInstallTarget(self, site) for site in self.options.sites])
		r.execute()


if __name__ == '__main__':
	Runner().run()
	
