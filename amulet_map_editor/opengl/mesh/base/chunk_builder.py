import numpy
from typing import Tuple, Dict, List

import minecraft_model_reader

from amulet_map_editor.opengl.mesh import new_empty_verts, TriMesh

_brightness_step = 0.15
_brightness_multiplier = {
    None: (1,)*3,
    'up': (1,)*3,
    'north': (1-_brightness_step,)*3,
    'south': (1-_brightness_step,)*3,
    'east': (1-_brightness_step*2,)*3,
    'west': (1-_brightness_step*2,)*3,
    'down': (1-_brightness_step*3,)*3,
}


class RenderChunkBuilder(TriMesh):
    """A class to define the logic to generate geometry from a block array"""

    def _get_model(self, block_temp_id: int) -> minecraft_model_reader.MinecraftMesh:
        raise NotImplementedError

    def _texture_bounds(self, texture):
        raise NotImplementedError

    @property
    def offset(self) -> numpy.ndarray:
        raise NotImplementedError

    def _get_block_data(self, blocks: numpy.ndarray) -> Tuple[numpy.ndarray, numpy.ndarray]:
        """Given a Chunk object will return the chunk arrays needed to generate geometry
        :returns: block array of the chunk, block array one block larger than the chunk, array of unique blocks"""
        larger_blocks = numpy.zeros(blocks.shape + numpy.array((2, 2, 2)), blocks.dtype)
        larger_blocks[1:-1, 1:-1, 1:-1] = blocks
        unique_blocks = numpy.unique(larger_blocks)
        return larger_blocks, unique_blocks

    def create_geometry(self):
        raise NotImplementedError

    def _set_verts(self, chunk_verts: List[numpy.ndarray], chunk_verts_translucent: List[numpy.ndarray]):
        if chunk_verts:
            self.verts = numpy.concatenate(chunk_verts, 0)
            self.verts_translucent = self.verts.size
        else:
            self.verts = new_empty_verts()

        if chunk_verts_translucent:
            chunk_verts_translucent.insert(0, self.verts)
            self.verts = numpy.concatenate(chunk_verts_translucent, 0)

        self.draw_count = int(self.verts.size // self._vert_len)

    def _create_lod0_multi(self, blocks: List[Tuple[numpy.ndarray, numpy.ndarray, Tuple[int, int, int]]]):
        chunk_verts = []
        chunk_verts_translucent = []
        for larger_blocks, unique_blocks, offset in blocks:
            chunk_verts_, chunk_verts_translucent_ = self._create_lod0_array(larger_blocks, unique_blocks, offset)
            chunk_verts += chunk_verts_
            chunk_verts_translucent += chunk_verts_translucent_
        self._set_verts(chunk_verts, chunk_verts_translucent)

    def _create_lod0(self, larger_blocks: numpy.ndarray, unique_blocks: numpy.ndarray):
        self._set_verts(
            *self._create_lod0_array(larger_blocks, unique_blocks)
        )

    def _create_lod0_array(self, larger_blocks: numpy.ndarray, unique_blocks: numpy.ndarray, offset: Tuple[int, int, int] = None) -> Tuple[List[numpy.ndarray], List[numpy.ndarray]]:
        """Create a numpy array for opaque geometry and a numpy array for """
        offset = offset or (0, 0, 0)
        blocks = larger_blocks[1:-1, 1:-1, 1:-1]
        transparent_array = numpy.zeros(larger_blocks.shape, dtype=numpy.uint8)
        models: Dict[int, minecraft_model_reader.MinecraftMesh] = {}
        for block_temp_id in unique_blocks:
            model = models[block_temp_id] = self._get_model(block_temp_id)
            transparent_array[larger_blocks == block_temp_id] = model.is_transparent

        def get_transparent_array(offset_transparent_array, transparent_array_):
            return numpy.logical_and(
                offset_transparent_array,  # if the next block is transparent
                numpy.logical_not(  # but is not the same block with transparency mode 1
                    (offset_transparent_array == 1) * (offset_transparent_array == transparent_array_)
                )
            )

        middle_transparent_array = transparent_array[1:-1, 1:-1, 1:-1]
        show_up = get_transparent_array(transparent_array[1:-1, 2:, 1:-1], middle_transparent_array)
        show_down = get_transparent_array(transparent_array[1:-1, :-2, 1:-1], middle_transparent_array)
        show_north = get_transparent_array(transparent_array[1:-1, 1:-1, :-2], middle_transparent_array)
        show_south = get_transparent_array(transparent_array[1:-1, 1:-1, 2:], middle_transparent_array)
        show_east = get_transparent_array(transparent_array[2:, 1:-1, 1:-1], middle_transparent_array)
        show_west = get_transparent_array(transparent_array[:-2, 1:-1, 1:-1], middle_transparent_array)

        show_map = {
            'up': show_up,
            'down': show_down,
            'north': show_north,
            'south': show_south,
            'east': show_east,
            'west': show_west
        }

        chunk_verts = []
        chunk_verts_translucent = []

        for block_temp_id, model in models.items():
            # for each unique blockstate in the chunk
            # get the model and the locations of the blocks
            model: minecraft_model_reader.MinecraftMesh
            all_block_locations = numpy.argwhere(blocks == block_temp_id)
            if not all_block_locations.size:
                continue
            where = None
            for cull_dir in model.faces.keys():
                # iterate through each cull direction
                # narrow down the blocks to what should be created for that cull direction
                if cull_dir is None:
                    block_locations = all_block_locations
                elif cull_dir in show_map:
                    if where is None:
                        where = tuple(all_block_locations.T)
                    block_locations = all_block_locations[show_map[cull_dir][where]]
                    if not block_locations.size:
                        continue
                else:
                    continue

                # the number of blocks and their offsets in chunk space
                block_count = len(block_locations)
                block_offsets = block_locations

                # the vertices in model space
                verts = model.verts[cull_dir].reshape((-1, 3))
                tverts = model.texture_coords[cull_dir].reshape((-1, 2))
                faces = model.faces[cull_dir]

                # each slice in the first axis is a new block, each slice in the second is a new vertex
                vert_table = numpy.zeros((block_count, faces.size, self._vert_len), dtype=numpy.float32)
                vert_table[:, :, :3] = verts[faces] + block_offsets[:, :].reshape((-1, 1, 3)) + self.offset + offset
                vert_table[:, :, 3:5] = tverts[faces]

                vert_index = 0
                for texture_index in model.texture_index[cull_dir]:
                    tex_bounds = self._texture_bounds(model.textures[texture_index])

                    vert_table[:, vert_index:vert_index+3, 5:9] = tex_bounds
                    vert_index += 3

                vert_table[:, :, 9:12] = model.tint_verts[cull_dir].reshape((-1, 3))[faces] * _brightness_multiplier[cull_dir]

                if model.is_transparent == 1:
                    chunk_verts_translucent.append(vert_table.ravel())
                else:
                    chunk_verts.append(vert_table.ravel())

        return chunk_verts, chunk_verts_translucent
