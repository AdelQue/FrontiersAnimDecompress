import bpy
from .animation.anim_import import FrontiersAnimImport
from .animation.anim_export import FrontiersAnimExport
from .skeleton.skeleton_export import HedgehogSkeletonExport

bl_info = {
    "name": "Sonic Frontiers Animation Tools",
    "author": "AdelQ, WistfulHopes",
    "version": (2, 0, "0 alpha 2"),
    "blender": (4, 1, 0),
    "location": "File > Import/Export",
    "description": "Animation and skeleton importer/exporter for Hedgehog Engine 2 games with compressed animations",
    "warning": "TEST VERSION, BROKEN FEATURES, NOT FOR USE, ",
    "doc_url": "https://hedgedocs.com/guides/hedgehog-engine/rangers/animation/import-export/",
    "tracker_url": "https://github.com/AdelQue/FrontiersAnimDecompress/issues/",
    "category": "Import-Export",
}


def register():
    bpy.utils.register_class(FrontiersAnimImport)
    bpy.types.TOPBAR_MT_file_import.append(FrontiersAnimImport.menu_func_import)

    bpy.utils.register_class(FrontiersAnimExport)
    bpy.types.TOPBAR_MT_file_export.append(FrontiersAnimExport.menu_func_export)

    bpy.utils.register_class(HedgehogSkeletonExport)
    bpy.types.TOPBAR_MT_file_export.append(HedgehogSkeletonExport.menu_func_export)


def unregister():
    bpy.utils.unregister_class(FrontiersAnimImport)
    bpy.types.TOPBAR_MT_file_import.remove(FrontiersAnimImport.menu_func_import)

    bpy.utils.unregister_class(FrontiersAnimExport)
    bpy.types.TOPBAR_MT_file_export.remove(FrontiersAnimExport.menu_func_export)

    bpy.utils.unregister_class(HedgehogSkeletonExport)
    bpy.types.TOPBAR_MT_file_export.remove(HedgehogSkeletonExport.menu_func_export)
