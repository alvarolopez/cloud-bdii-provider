# This provider is for an OpenNebula middleware using the rOCCI server. Part of
# the information is retreived from OpenNebula, part of it is retreived from
# rOCCI directly. To retreive flavour information, rOCCI

import os
import sys
import urllib2
import json
import re
from xml.dom import minidom

from cloud_bdii import providers


class OpenNebulaROCCIProvider(providers.BaseProvider):
    def __init__(self, opts):
        super(OpenNebulaROCCIProvider, self).__init__(opts)

        self.on_auth = opts.on_auth
        self.on_rpcxml_endpoint = opts.on_rpcxml_endpoint

        if not self.on_auth or self.on_auth is None:
            f = open(os.path.expanduser('~') + '/.one/one_auth', 'w')
            self.on_auth = f.read()
            f.close()

        if self.on_auth is None:
            print >> sys.stderr, ('ERROR, You must provide a on_auth '
                                  'via either --on-auth or env[ON_AUTH]'
                                  'or ON_AUTH file')
            sys.exit(1)

        if not self.on_rpcxml_endpoint:
            print >> sys.stderr, ('You must provide an OpenNebula RPC-XML '
                                  'endpoint via either --on-rpcxml-endpoint or'
                                  ' env[ON_RPCXML_ENDPOINT]')
            sys.exit(1)

        self.static = providers.static.StaticProvider(opts)
        self.onprovider = providers.opennebula.OpenNebulaProvider(opts)

    # The flavours are retreived directly from rOCCI-server configuration
    # files. If the script has no access to them, you can set the directory to
    # None and configuration files specified in the YAML configuration.
    def get_templates(self):

        if (('template_dir' not in self.static.yaml['compute']) or
                (not self.static.yaml['compute']['template_dir']) or
                (self.static.yaml['compute']['template_dir'] is None)):
            # revert to static
            return self.static.get_templates()

        defaults = {'platform': 'amd64', 'network': 'private'}
        defaults.update(self.static.get_template_defaults(prefix=True))

        # Try to parse template dir
        template_dir = self.static.yaml['compute']['template_dir']
        dlist = os.listdir(template_dir)
        flavors = {}
        flid = 0
        for d in dlist:
            jf = open(template_dir + '/' + d, 'r')
            jd = json.load(jf)
            jf.close()

            aux = defaults.copy()
            aux.update({'template_id': 'resource_tpl#%s' % jd['mixins'][0]['term'],  # noqa
                        'template_memory': jd['mixins'][0]['attributes']['occi']['compute']['cores']['Default'],  # noqa
                        'template_cpu': int(jd['mixins'][0]['attributes']['occi']['compute']['memory']['Default']*1024),  # noqa
                        'template_description': jd['mixins'][0]['title']})  # noqa

            flavors[flid] = aux
            flid = flid + 1

        return flavors

    def get_images(self):
        images = {}

        template = {
            'image_name': None,
            'image_description': None,
            'image_version': None,
            'image_marketplace_id': None,
            'image_id': None,
            'image_os_family': None,
            'image_os_name': None,
            'image_os_version': None,
            'image_platform': 'amd64',
        }
        defaults = self.static.get_image_defaults(prefix=True)

        # Perform request for data (Images in rOCCI are set to OpenNebula
        # templates, so here we need to list the templates. Anyway, we also
        # need to get additional parameters from the images, so we will list
        # the images for OpenNebula too)
        images_ON = self.onprovider.get_images()
        requestdata = '''<?xml version='1.0' encoding='UTF-8'?>
<methodCall>
<methodName>one.templatepool.info</methodName>
<params>
<param><value><string>'%s'</string></value></param>
<param><value><i4>-2</i4></value></param>
<param><value><i4>-1</i4></value></param>
<param><value><i4>-1</i4></value></param>
</params>
</methodCall>
''' % self.on_auth

        req = urllib2.Request(self.on_rpcxml_endpoint, requestdata)
        response = urllib2.urlopen(req)

        xml  = response.read()
        xmldoc = minidom.parseString(xml)
        itemlist = xmldoc.getElementsByTagName('string')

        id = 0
        images = {}
        for s in itemlist:
            xmldocimage = minidom.parseString(s.firstChild.nodeValue)
            itemlistimage = xmldocimage.getElementsByTagName('VMTEMPLATE')
            for i in itemlistimage:
                aux = template.copy()
                aux.update(defaults)
                aux.update({
                    'image_name': i.getElementsByTagName(
                        'NAME')[0].firstChild.nodeValue
                })
                # Generate image uiid as rOCCI does
                tmpimgid = i.getElementsByTagName('NAME')[0].firstChild.nodeValue  # noqa
                tmpimgid = tmpimgid.lower()
                tmpimgid = re.sub(r'\s[^0-9a-zA-Z]\s', '_', tmpimgid)
                tmpimgid = re.sub(r'\s_+\s', '_', tmpimgid)
                tmpimgid = tmpimgid.strip('_')
                tmpimgid = 'os_tpl#uuid_%s_%s' % (tmpimgid, i.getElementsByTagName('ID')[0].firstChild.nodeValue)  # noqa
                aux.update({'image_id': tmpimgid})
                if i.getElementsByTagName('DESCRIPTION').length > 0:
                    aux.update({'image_description': i.getElementsByTagName('DESCRIPTION')[0].firstChild.nodeValue})  # noqa
                # Get additional image metadata from the first associated disk
                # image.
                # NOTE: If this is not the OS template, we have a problem
                tmpdsk = i.getElementsByTagName('DISK')
                tmpdskl = ''
                for d in tmpdsk:
                    tmpel = d.getElementsByTagName('IMAGE')
                    if tmpel.length > 0:
                        tmpdskl = tmpel[0].firstChild.nodeValue
                        break

                if tmpdskl:
                    for i in images_ON:
                        i = images_ON[i]
                        if i['image_name'] == tmpdskl:
                            for v in i:
                                if v not in aux or aux[v] is None:
                                    aux[v] = i[v]
                            break

                images[id] = aux
                id = id + 1

        return images
