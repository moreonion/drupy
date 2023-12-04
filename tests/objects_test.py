"""Tests objects."""

import os.path
import pathlib
from unittest import TestCase, mock

import pytest

from drupy import objects, utils
from drupy.objects import DrupalOrgProject, TarballExtract, UrllibDownloader


def test_loading_yaml_config():
    """Test loading config from a yaml file."""
    path = pathlib.Path(__file__).parent / "data" / "test.yaml"
    parser = objects.get_parser(path)
    with open(path, encoding="utf-8") as config_file:
        data = parser(config_file)
    assert data == {"foo": 42}


class DrupalOrgProjectTest(TestCase):
    """Test the object for drupal.org projects."""

    def test_split_project(self):
        """Test splitting the project key into name and version information."""
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
        with pytest.raises(ValueError):
            DrupalOrgProject.split_project("sentry-php-1.6.2")

    def test_is_valid(self):
        """Test the is_valid methods."""
        # Valid package spec without declaring type.
        p = DrupalOrgProject(None, {"dirname": "campaignion-7.x-1.0"})
        assert p.is_valid()

        # Invalid package spec but declaring type.
        p = DrupalOrgProject(
            None,
            {
                "dirname": "testitt",
                "build": [{}],
                "type": "drupal.org",
            },
        )
        assert p.is_valid()

        # Invalid package spec without declaring type.
        p = DrupalOrgProject(None, {"dirname": "testitt"})
        assert not p.is_valid()


class TarballExtractTest:
    """Test extracting a tarball."""

    @staticmethod
    def test_libraries(temp_dir):
        """Test whether the top-level directory is properly stripped."""
        fake_runner = mock.Mock(options=mock.Mock(verbose=False))
        dl = UrllibDownloader(
            fake_runner,
            config={"url": "https://ftp.drupal.org/files/projects/libraries-7.x-2.3.tar.gz"},
        )
        ex = TarballExtract(
            fake_runner, config={"localpath": dl.download("", temp_dir).localpath()}
        )
        ex.apply_to(temp_dir + "/libraries")
        assert os.path.exists(temp_dir + "/libraries/libraries.module")

    @staticmethod
    def test_highcharts(temp_dir):
        """Highcharts is a zip-file without any directories to strip."""
        fake_runner = mock.Mock(options=mock.Mock(verbose=False))
        dl = UrllibDownloader(
            fake_runner, config={"url": "http://code.highcharts.com/zips/Highcharts-4.2.7.zip"}
        )
        ex = TarballExtract(
            fake_runner, config={"localpath": dl.download("", temp_dir).localpath()}
        )
        ex.apply_to(temp_dir + "/highcharts")
        os.path.exists(temp_dir + "/highcharts/js/highcharts.js")

    @staticmethod
    def test_normalizing_permissions(temp_dir):
        """Check if permissions are normalized for ckeditor-4.16.1."""
        fake_runner = mock.Mock(options=mock.Mock(verbose=False))
        ckeditor_url = (
            "https://download.cksource.com/CKEditor/CKEditor/"
            "CKEditor%204.16.1/ckeditor_4.16.1_standard.zip"
        )
        dl = UrllibDownloader(fake_runner, config={"url": ckeditor_url})
        ex = TarballExtract(
            fake_runner, config={"localpath": dl.download("", temp_dir).localpath()}
        )
        ex.apply_to(temp_dir)
        umask = utils.get_umask()
        assert pathlib.Path(temp_dir).joinpath("skins").stat().st_mode & 0o777 == 0o777 & ~umask
