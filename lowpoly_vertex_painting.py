import bpy
import bmesh
from bpy_extras import view3d_utils
from mathutils import Quaternion, Vector, Color
from mathutils.bvhtree import BVHTree
from collections import deque
from math import sqrt, floor

bl_info = {
    "name": "Low-Poly Vertex Paint Tools",
    "description": "Tools to improve low-poly vertex painting.",
    "author": "Luca Harris",
    "version": (1, 0),
    "wiki_url": "https://github.com/lucatronica/blender-lowpoly-vertex-painting",
    "blender": (2, 90, 0),
    "category": "3D View",
}


# We use a custom brush for each of our tools.
# This allows native operators to use the tool's selected color (e.g. "Set Vertex Colors"/Shift-K). 
# It also means the native color picker tools work for our tools.
BRUSH_FILL = "Vertex Color Fill"
BRUSH_DRAW_FACE = "Vertex Color Draw Face"

for brush_name in [BRUSH_FILL, BRUSH_DRAW_FACE]:
    if brush_name not in bpy.data.brushes:
        brush = bpy.data.brushes.new(brush_name, mode="VERTEX_PAINT")
        brush.color = Color((1.0, 1.0, 1.0))

def set_brush_active(context):
    # Get current brush name
    current_tool = context.workspace.tools.from_space_view3d_mode("PAINT_VERTEX", create=False)

    brush_name = None
    if current_tool.idname == VertexPaintFillTool.bl_idname:
        brush_name = BRUSH_FILL
    elif current_tool.idname == VertexPaintDrawFaceTool.bl_idname:
        brush_name = BRUSH_DRAW_FACE
    else:
        return

    # XXX Since we're using the "Draw" brush slot, the draw tool will try to
    # use the brush we assign as the active vertex_paint brush.
    # So try to preserve the brush for the draw tool!
    # (Note exiting vertex paint mode while our tools are selected will cause
    # the draw tool to equip our brush, not sure how to fix that...)
    old_brush = context.tool_settings.vertex_paint.tool_slots[0].brush
    context.tool_settings.vertex_paint.brush = bpy.data.brushes[brush_name]
    context.tool_settings.vertex_paint.tool_slots[0].brush = old_brush

# Brush color getter/setters, used in tool properties.
def get_fill_color(self):
    return bpy.data.brushes[BRUSH_FILL].color

def set_fill_color(self, value):
    bpy.data.brushes[BRUSH_FILL].color = value

def get_draw_face_color(self):
    return bpy.data.brushes[BRUSH_DRAW_FACE].color

def set_draw_face_color(self, value):
    bpy.data.brushes[BRUSH_DRAW_FACE].color = value

# returns (result, location, normal, index)
def pick_vertex(context, obj, region_x, region_y):
    # get mouse ray in object space
    region = context.region
    rv3d = context.region_data
    coord = region_x, region_y
    world_ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    world_ray_direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)

    mwi = obj.matrix_world.inverted()
    ray_origin = mwi @ world_ray_origin
    ray_direction = (mwi @ (world_ray_origin + world_ray_direction)) - ray_origin

    # ray cast
    return obj.ray_cast(ray_origin, ray_direction)

# pick vertex color at index, using weighted average of surrounding points
# returns (result, color4, index)
def pick_vertex_color(context, obj, region_x, region_y):
    result, location, normal, index = pick_vertex(context, obj, region_x, region_y)

    color = Vector((0.0, 0.0, 0.0, 0.0))
    if result:
        me = obj.data
        colors = me.vertex_colors.active.data
        location_vector = Vector(location)
        total = 0.0

        for loop_index in me.polygons[index].loop_indices:
            loop_position = me.vertices[me.loops[loop_index].vertex_index].co
            distance = (location_vector - loop_position).length
            total += distance

            loop_color = colors[loop_index].color
            color[0] += loop_color[0] * distance
            color[1] += loop_color[1] * distance
            color[2] += loop_color[2] * distance
            color[3] += loop_color[3] * distance
        
        if total > 0.0:
            color /= total

    return result, color, index

# returns a set of loops
def connected_loops(bm, starting_faces, color=None, tolerance=0.001, traverse_vertices=False, selected_faces=False, selected_vertices=False):
    color_layer = bm.loops.layers.color.active
    
    face_set = set(starting_faces)
    face_queue = deque(face_set);
    loop_set = set()

    if color is None:
        color = face_color(bm, next(iter(face_set)))

    while len(face_queue) > 0:
        face = face_queue.pop()

        # make sure we can visit this face
        if not selected_faces or face.select:
            # inspect all loops on this face
            for loop in face.loops:
                if color_equal(loop[color_layer], color, tolerance):
                    # save loop if we're allowed to
                    if not selected_vertices or loop.vert.select:
                        loop_set.add(loop)

                    # see if we can travel to neighboring faces :)
                    for connected_loop in (loop.vert.link_loops if traverse_vertices else loop.link_loops):
                        connected_face = connected_loop.face
                        if connected_face not in face_set and color_equal(connected_loop[color_layer], color, tolerance):
                            face_set.add(connected_face)
                            face_queue.appendleft(connected_face)
    
    return loop_set

# if two color vector4s are equal
def color_equal(v1, v2, tolerance):
    return (v1 - v2).length_squared / 3.0 <= tolerance

# get the average color of a face
def face_color(bm, face):
    color_layer = bm.loops.layers.color.active

    color = Vector((0.0, 0.0, 0.0, 0.0))
    for loop in face.loops:
        color += loop[color_layer]

    return color / len(face.loops)


class VertexPaintColorSample(bpy.types.Operator):
    """Sample vertex color."""
    bl_idname = "paint.vertex_color_sample"
    bl_label = "Sample vertex color"
    bl_options = {"UNDO"}

    x: bpy.props.IntProperty()
    y: bpy.props.IntProperty()

    def execute(self, context):
        result, color, _ = pick_vertex_color(context, bpy.context.active_object, self.x, self.y)
        if result:
            context.tool_settings.vertex_paint.brush.color = Color(color[:3])
            context.area.tag_redraw()  # make toolbar color update
        return {"FINISHED"}
    
    def invoke(self, context, event):
        self.x = event.mouse_region_x
        self.y = event.mouse_region_y
        return self.execute(context)


class VertexPaintFillOperator(bpy.types.Operator):
    bl_idname = "paint.vertex_fill"
    bl_label = "Vertex Paint Fill"
    bl_options = {"UNDO"}

    x: bpy.props.IntProperty()
    y: bpy.props.IntProperty()

    color: bpy.props.FloatVectorProperty(
        name="Color",
        description="Set's the fill color",
        subtype="COLOR_GAMMA",
        default=(1.0, 1.0, 1.0),
        min=0.0,
        max=1.0,
        get=get_fill_color,
        set=set_fill_color,
    )

    tolerance: bpy.props.FloatProperty(
        name="Tolerance",
        description="Controls the similarity for colors to be considered equal. A lower value means only more similar colors will be selected",
        subtype ="FACTOR",
        default=0.005,
        precision=3,
        min=0.0,
        max=1.0,
    )

    continuous: bpy.props.BoolProperty(
        name="Continuous",
        description="If the fill should only traverse connected faces",
        default=True,
    )

    vertices: bpy.props.BoolProperty(
        name="Traverse Vertices",
        description="If enabled then the fill will traverse vertex corners",
        default=False,
    )

    def execute(self, context):
        fill_op_main(context, self.x, self.y, self.color, self.tolerance, self.continuous, self.vertices)
        return {"FINISHED"}
    
    def invoke(self, context, event):
        self.x = event.mouse_region_x
        self.y = event.mouse_region_y
        return self.execute(context)

def fill_op_main(context, x, y, color, tolerance, continuous, traverse_vertices):
    obj = context.vertex_paint_object

    result, target_color, index = pick_vertex_color(context, obj, x, y)

    if result:
        me = obj.data
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.faces.ensure_lookup_table()
        face = bm.faces[index]

        color4 = Vector((color[0], color[1], color[2], 1.0))
        color_layer = bm.loops.layers.color.active

        if continuous:
            for loop in connected_loops(bm, [face], color=target_color, tolerance=tolerance, traverse_vertices=traverse_vertices, selected_faces=me.use_paint_mask, selected_vertices=me.use_paint_mask_vertex):
                loop[color_layer] = color4
        else:
            for face in bm.faces:
                for loop in face.loops:
                    if color_equal(target_color, loop[color_layer], tolerance):
                        loop[color_layer] = color4
        
        bm.to_mesh(me)
        bm.free()
        me.update()


class VertexDrawFaceOperator(bpy.types.Operator):
    bl_idname = "paint.vertex_draw_face"
    bl_label = "Vertex Draw Face"
    bl_options = {"UNDO"}

    x1: bpy.props.IntProperty()
    y1: bpy.props.IntProperty()
    x2: bpy.props.IntProperty()
    y2: bpy.props.IntProperty()

    color: bpy.props.FloatVectorProperty(
        name="Color",
        description="Set's the fill color",
        subtype="COLOR_GAMMA",
        default=(1.0, 1.0, 1.0),
        min=0.0,
        max=1.0,
        get=get_draw_face_color,
        set=set_draw_face_color,
    )

    def invoke(self, context, event):
        self.x1 = self.x2 = event.mouse_region_x
        self.y1 = self.y2 = event.mouse_region_y

        # Load the object's BVH, we'll use it for ray casting
        self.bvh = BVHTree.FromObject(context.vertex_paint_object, context.view_layer.depsgraph)

        # Draw the starting pixel
        draw_face_op_main(self, context)

        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            return {"FINISHED"}
        
        if event.type == "MOUSEMOVE":
            # Draw line between last position and current position
            self.x1 = self.x2;
            self.y1 = self.y2;
            self.x2 = event.mouse_region_x
            self.y2 = event.mouse_region_y
            draw_face_op_main(self, context)

        return {"RUNNING_MODAL"}

def draw_face_op_main(self, context):
    x1 = self.x1
    y1 = self.y1
    x2 = self.x2
    y2 = self.y2
    bvh = self.bvh
    color_array = tuple(self.color) + (1.0,)

    obj = context.vertex_paint_object
    me = obj.data
    selected_faces_only = me.use_paint_mask or me.use_paint_mask_vertex

    dx = x1 - x2
    dy = y1 - y2
    length = sqrt(dx * dx + dy * dy)
    n = max(1, floor(length / 2)) # check every 2 pixels

    mwi = obj.matrix_world.inverted()
    region = context.region
    rv3d = context.region_data

    # iterate pixels
    for i in range(0, n):
        t = 0.5 if n == 1 else i / (n - 1)
        x = (1 - t) * x1 + t * x2
        y = (1 - t) * y1 + t * y2
        coord = x, y

        world_ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        world_ray_direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)

        ray_origin = mwi @ world_ray_origin
        ray_direction = (mwi @ (world_ray_origin + world_ray_direction)) - ray_origin

        result, _, index, _ = bvh.ray_cast(ray_origin, ray_direction)

        if result:
            me = obj.data
            colors = me.vertex_colors.active.data
            polygon = me.polygons[index]

            # If enabled, only draw on select faces/vertices
            if not selected_faces_only or polygon.select:
                for loop_index in polygon.loop_indices:
                    colors[loop_index].color = color_array

# XXX We use this gizmo to detect when one of our Vertex Paint tools has been selected.
# When we select a tool, we want to make our custom brush the active brush.
class VertexPaintToolsGizmoGroup(bpy.types.GizmoGroup):
    bl_idname = "OBJECT_GGT_vertex_paint_tool_hack"
    bl_label = "Test Light Widget"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D"}

    def setup(self, context):
        def op():
            set_brush_active(context)
            return None
        bpy.app.timers.register(op)


class VertexPaintFillTool(bpy.types.WorkSpaceTool):
    bl_space_type = "VIEW_3D"
    bl_context_mode = "PAINT_VERTEX"
    bl_idname = "vertex_paint_fill"
    bl_label = "Fill"
    bl_description = "Fill connected faces with the active color"
    bl_icon = "ops.paint.weight_fill"
    bl_widget = VertexPaintToolsGizmoGroup.bl_idname
    bl_keymap = (
        (VertexPaintFillOperator.bl_idname, {"type": "LEFTMOUSE", "value": "PRESS"}, {}),
        (VertexPaintColorSample.bl_idname, {"type": "S", "value": "PRESS"}, {}),
    )

    icon_small = "IMAGE"

    def draw_settings(context, layout, tool):
        props = tool.operator_properties(VertexPaintFillOperator.bl_idname)
        layout.prop(props, "color", text="")
        layout.prop(props, "tolerance")
        layout.prop(props, "continuous")

        row = layout.row()
        row.enabled = props.continuous
        row.prop(props, "vertices")


class VertexPaintDrawFaceTool(bpy.types.WorkSpaceTool):
    bl_space_type = "VIEW_3D"
    bl_context_mode = "PAINT_VERTEX"
    bl_idname = "vertex_paint_draw_face"
    bl_label = "Draw Face"
    bl_description = "Draw the active color onto faces"
    bl_icon = "ops.gpencil.draw.line"
    bl_cursor = "PAINT_BRUSH"
    bl_widget = VertexPaintToolsGizmoGroup.bl_idname
    bl_keymap = (
        (VertexDrawFaceOperator.bl_idname, {"type": "LEFTMOUSE", "value": "PRESS"}, {}),
        (VertexPaintColorSample.bl_idname, {"type": "S", "value": "PRESS"}, {}),
    )

    icon_small = "BRUSH_DATA"

    def draw_settings(context, layout, tool):
        props = tool.operator_properties(VertexDrawFaceOperator.bl_idname)
        layout.prop(props, "color", text="")


class SelectLinkedFacesByVertexColor(bpy.types.Operator):
    """Select linked faces by vertex color."""
    bl_idname = "mesh.select_linked_vertex_color"
    bl_label = "Select Linked Faces by Vertex Color"
    bl_options = {"UNDO", "REGISTER"}

    @classmethod
    def poll(cls, context):
        obj = context.edit_object
        return (obj is not None and obj.data.vertex_colors.active is not None and obj.data.total_face_sel > 0)

    def execute(self, context):
        select_linked_by_color_op_main(context)
        return {"FINISHED"}

def select_linked_by_color_op_main(context):
    me = context.edit_object.data
    bm = bmesh.from_edit_mesh(me)
    
    for loop in connected_loops(bm, filter(lambda face : face.select, bm.faces), traverse_vertices=True):
        loop.face.select = True
    
    bm.select_mode = {"FACE"}
    bm.select_flush_mode()
    me.update()

def mesh_edit_select_menu_draw(self, context):
    layout = self.layout
    layout.operator(SelectLinkedFacesByVertexColor.bl_idname, text="Vertex Color")


class SelectSimilarByVertexColor(bpy.types.Operator):
    """Select geometry by vertex color."""
    bl_idname = "mesh.select_similar_vertex_color"
    bl_label = "Select similar geometry by Vertex Color"
    bl_options = {"UNDO", "REGISTER"}

    tolerance: bpy.props.FloatProperty(
        name="Tolerance",
        description="Controls the similarity for colors to be considered equal. A lower value means only more similar colors will be selected",
        subtype ="FACTOR",
        default=0.005,
        precision=3,
        min=0.0,
        max=1.0,
    )

    @classmethod
    def poll(cls, context):
        obj = context.edit_object
        return (obj is not None and obj.data.vertex_colors.active is not None and obj.data.total_face_sel > 0)

    def execute(self, context):
        select_similar_by_color_op_main(context, self.tolerance)
        return {"FINISHED"}

def select_similar_by_color_op_main(context, tolerance):
    me = context.edit_object.data
    bm = bmesh.from_edit_mesh(me)
    color_layer = bm.loops.layers.color.active

    color = face_color(bm, next(iter(filter(lambda face : face.select, bm.faces))))

    for face in bm.faces:
        if color_equal(color, face_color(bm, face), tolerance):
            face.select = True
    
    bm.select_mode = {"FACE"}
    bm.select_flush_mode()
    me.update()

def mesh_edit_select_similar_menu_draw(self, context):
    layout = self.layout
    layout.operator(SelectSimilarByVertexColor.bl_idname, text="Vertex Color")


classes = (
    VertexPaintFillOperator,
    VertexDrawFaceOperator,
    SelectLinkedFacesByVertexColor,
    SelectSimilarByVertexColor,
    VertexPaintColorSample,
    VertexPaintToolsGizmoGroup,
)

def register():
    bpy.utils.register_tool(VertexPaintDrawFaceTool, separator=True)
    bpy.utils.register_tool(VertexPaintFillTool)
    bpy.types.VIEW3D_MT_edit_mesh_select_linked.append(mesh_edit_select_menu_draw)
    bpy.types.VIEW3D_MT_edit_mesh_select_similar.append(mesh_edit_select_similar_menu_draw)
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    bpy.utils.unregister_tool(VertexPaintDrawFaceTool)
    bpy.utils.unregister_tool(VertexPaintFillTool)
    bpy.types.VIEW3D_MT_edit_mesh_select_linked.remove(mesh_edit_select_menu_draw)
    bpy.types.VIEW3D_MT_edit_mesh_select_similar.remove(mesh_edit_select_similar_menu_draw)
    for cls in classes:
        bpy.utils.unregister_class(cls)

# testing
if __name__ == "__main__":
    register()
