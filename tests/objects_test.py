import os.path
import shutil
import pathlib
from unittest import TestCase

import pytest

from drupy.objects import DrupalOrgProject, TarballExtract, UrllibDownloader
from drupy import utils


class DrupalOrgProjectTest(TestCase):
    def test_split_project(self):
        assert DrupalOrgProject.split_project("campaignion-7.x-1.5+pr32") == (
            "campaignion",
            "7.x",
            "1.5",
            ("pr32",),
        )
        assert DrupalOrgProject.split_project("campaignion-7.x-1.0-rc1") == (
            "campaignion",
            "7.x",
            "1.0-rc1",
            tuple(),
        )
        assert DrupalOrgProject.split_project("campaignion-7.x-1.x-dev") == (
            "campaignion",
            "7.x",
            "1.x-dev",
            tuple(),
        )
        with pytest.raises(ValueError) as e:
            DrupalOrgProject.split_project("sentry-php-1.6.2")

    def test_is_valid(self):
        # Valid package spec without declaring type.
        p = DrupalOrgProject(None, dict(dirname="campaignion-7.x-1.0"))
        assert p.is_valid()

        # Invalid package spec but declaring type.
        p = DrupalOrgProject(
            None,
            dict(
                dirname="testitt",
                build=[{}],
                type="drupal.org",
            ),
        )
        assert p.is_valid()

        # Invalid package spec without declaring type.
        p = DrupalOrgProject(None, dict(dirname="testitt"))
        assert not p.is_valid()


class TarballExtractTest:
    """Test extracting a tarball."""

    @staticmethod
    def test_libraries(temp_dir):
        """Test whether the top-level directory is properly stripped."""

        class Fakerunner:
            class options:
                verbose = False

        dl = UrllibDownloader(
            Fakerunner,
            config=dict(url="https://ftp.drupal.org/files/projects/libraries-7.x-2.3.tar.gz"),
        )
        ex = TarballExtract(
            Fakerunner, config=dict(localpath=dl.download("", temp_dir).localpath())
        )
        ex.apply_to(temp_dir + "/libraries")
        assert os.path.exists(temp_dir + "/libraries/libraries.module")

    @staticmethod
    def test_highcharts(temp_dir):
        """Highcharts is a zip-file without any directories to strip."""

        class Fakerunner:
            class options:
                verbose = False

        dl = UrllibDownloader(
            Fakerunner, config=dict(url="http://code.highcharts.com/zips/Highcharts-4.2.7.zip")
        )
        ex = TarballExtract(
            Fakerunner, config=dict(localpath=dl.download("", temp_dir).localpath())
        )
        ex.apply_to(temp_dir + "/highcharts")
        os.path.exists(temp_dir + "/highcharts/js/highcharts.js")

    @staticmethod
    def test_normalizing_permissions(temp_dir):
        """Check if permissions are normalized for ckeditor-4.16.1."""

        class Fakerunner:
            class options:
                verbose = False

        dl = UrllibDownloader(
            Fakerunner, config=dict(url="https://download.cksource.com/CKEditor/CKEditor/CKEditor%204.16.1/ckeditor_4.16.1_standard.zip")
        )
        ex = TarballExtract(
            Fakerunner, config=dict(localpath=dl.download("", temp_dir).localpath())
        )
        ex.apply_to(temp_dir)
        umask = utils.get_umask()
        assert pathlib.Path(temp_dir).joinpath("skins").stat().st_mode & 0o777 == 0o777 & ~umask
