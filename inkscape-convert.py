# encoding: utf-8

# inkscape-convert - Convert svg files to pdf
# Copyright (C) 2009 Michael Budde

import TaskGen

TaskGen.declare_chain(
    name='inkscape-svg-convert',
    action='${INKSCAPE} ${INKSCAPEFLAGS} --export-pdf=${TGT} ${SRC}',
    ext_in='.svg',
    ext_out='.pdf',
    reentrant=False)

def detect(conf):
    conf.find_program('inkscape', var='INKSCAPE', mandatory=True)
    conf.env['INKSCAPEFLAGS'] = ''
