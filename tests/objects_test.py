from unittest import TestCase

from drupy.objects import DrupalOrgProject


class DrupalOrgProjectTest(TestCase):

    def test_split_project(self):
        assert DrupalOrgProject.split_project('campaignion-7.x-1.5+pr32') == \
            ('campaignion', '7.x', '1.5', ('pr32', ))
        assert DrupalOrgProject.split_project('campaignion-7.x-1.0-rc1') == \
            ('campaignion', '7.x', '1.0-rc1', tuple())

    def test_is_valid(self):
        # Valid package spec without declaring type.
        p = DrupalOrgProject(None, dict(dirname='campaignion-7.x-1.0'))
        assert p.isValid()

        # Invalid package spec but declaring type.
        p = DrupalOrgProject(None, dict(
            dirname='testitt',
            build=[{}],
            type='drupal.org',
        ))
        assert p.isValid()

        # Invalid package spec without declaring type.
        p = DrupalOrgProject(None, dict(dirname='testitt'))
        assert not p.isValid()
