#%%
%matplotlib widget
import itertools
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np
import os

from dmfwizard.types import BoardDesign, Grid, Peripheral
from dmfwizard.io import load_peripheral
from dmfwizard.construct import Constructor, reduce_board_to_electrodes, crenellate_grid, offset_polygon
from dmfwizard.crenellation import crenellate_electrodes
from dmfwizard.kicad import save_board

# Define size of the electrode grids
GRID_PITCH = 2.5

# Define shape of the electrode crenellations
MARGIN = 0.15 # Space to leave between the corners and the start of crenellations on each edge
NUM_DIGITS = 5 # Number of points on each edge
THETA = 30 # Angle of points

# Copper-to-copper clearance and origin within the kicad PCB
CLEARANCE = 0.11
BOARD_ORIGIN = [162.5, 62.25]

GLASS_HEIGHT = 50
# Total size of reservoir in Y dimension
RESERVOIR_HEIGHT = 12.5
# Amount of reservoir which should overhang the glass plate edge
RESERVOIR_OVERHANG = 1

RESERVOIR_X_POSITIONS = [5, 10, 15]
RESERVOIR_Y_POSITION = 11

# Define position and size of the grid
GRID_WIDTH = 21
GRID_HEIGHT = 18
GRID_ORIGIN = (
    75.0/2 - GRID_WIDTH*GRID_PITCH/2,
    GLASS_HEIGHT - RESERVOIR_HEIGHT - (RESERVOIR_Y_POSITION + 1) * GRID_PITCH + RESERVOIR_OVERHANG)

grid_design = """\
 X  X  X  X  X  X  X
 X  X  X  X  X  X  X
 XXXXXXXXXXXXXXXXXXX
 X  X  X  X  X  X  X
 X  X  X  X  X  X  X
          X
          X
 X  X  X  X  X  X  X
 X  X  X  X  X  X  X
XXXXXXXXXXXXXXXXXXXXX
X    X    X    X    X
X    X    X    X    X
X                   X
X                   X
X                   X
X                   X
X                   X
X                   X
"""

# Create board and grids
board = BoardDesign()
grid = Grid(GRID_ORIGIN, (GRID_WIDTH, GRID_HEIGHT), GRID_PITCH)
board.grids.append(grid)
construct = Constructor()

construct.fill_ascii(grid, grid_design)

# Create reservoirs
reservoir_origin = np.add(GRID_ORIGIN, (0.5 * GRID_PITCH, 0.0))



for x_offset in RESERVOIR_X_POSITIONS:
    construct.add_peripheral(
        board,
        load_peripheral('peripherals/four_tier_reservoir.json'),
        np.add(reservoir_origin, np.multiply((x_offset, RESERVOIR_Y_POSITION + 1), GRID_PITCH)).tolist(),
        np.deg2rad(0))   

# Create copy of the board to crenellate. We will use the un-crenellated version for
# generating the board definition file.
crenellated_board = board.copy()

# Create interwoven fingers between neighboring electrodes
crenellate_grid(crenellated_board.grids[0], NUM_DIGITS, THETA, MARGIN*GRID_PITCH)

# Crenellate interface between reservoirs and grid
for i, x_offset in enumerate(RESERVOIR_X_POSITIONS):
    crenellate_electrodes(
        crenellated_board.grids[0].electrodes[(x_offset, RESERVOIR_Y_POSITION)],
        crenellated_board.peripherals[i].electrode('A'),
        NUM_DIGITS,
        THETA,
        MARGIN*GRID_PITCH
    )

# Get list of all electrodes with polygons in global board coordinates
electrodes = reduce_board_to_electrodes(board)

fig, ax = plt.subplots()
# Add grid outlines for reference
def draw_grid(ax, grid):
    for col, row in itertools.product(range(grid.size[0]), range(grid.size[1])):
        ax.add_patch(patches.Rectangle(
            (grid.pitch * col + grid.origin[0], grid.pitch * row + grid.origin[1]),
            grid.pitch,
            grid.pitch,
            fill=False,
            color='yellow')
        )
draw_grid(ax, board.grids[0])
for e in electrodes:
    ax.add_patch(patches.Polygon(offset_polygon(e.offset_points(), -0.1), fill=False))

print(f"Total electrodes: {len(electrodes)}")

# Add 50x75mm border for reference
ax.add_patch(patches.Rectangle((0, 0), 75, 50, fill=False, color='green'))
# Add cover margins that shows the exposed area of the top plate
ax.add_patch(patches.Rectangle((2.5, 4.0), 75-5, 50, fill=False, color='cyan'))
ax.autoscale()
ax.axis('square')
ax.invert_yaxis()
plt.show()

# %%
# Write KiCad footprints and layout.yml file for kicad
projdir = path = os.path.abspath(os.path.dirname(__file__))
save_board(crenellated_board, BOARD_ORIGIN, projdir, CLEARANCE)
# %%
# Generate the 'layout' property of a board definition file

# First, get electrode refdes to pin mapping from pcb file, based on net names
# Then, map the board grids and peripherals to the board definition format. 
# Finally, encode to JSON using the custom encoder for more readable output.

from dmfwizard.kicad import extract_electrode_nets
import json
import re

class CompactJSONEncoder(json.JSONEncoder):
    """A JSON Encoder that puts small lists on single lines."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.indentation_level = 0

    def encode(self, o):
        """Encode JSON object *o* with respect to single line lists."""

        if isinstance(o, (list, tuple)):
            if self._is_single_line_list(o):
                return "[" + ", ".join(json.dumps(el) for el in o) + "]"
            else:
                self.indentation_level += 1
                output = [self.indent_str + self.encode(el) for el in o]
                self.indentation_level -= 1
                return "[\n" + ",\n".join(output) + "\n" + self.indent_str + "]"

        elif isinstance(o, dict):
            self.indentation_level += 1
            output = [self.indent_str + f"{json.dumps(k)}: {self.encode(v)}" for k, v in o.items()]
            self.indentation_level -= 1
            return "{\n" + ",\n".join(output) + "\n" + self.indent_str + "}"

        else:
            return json.dumps(o)

    def _is_single_line_list(self, o):
        if isinstance(o, (list, tuple)):
            return not any(isinstance(el, (list, tuple, dict)) for el in o)\
                   and len(o) <= 2\
                   and len(str(o)) - 2 <= 60

    @property
    def indent_str(self) -> str:
        return " " * self.indentation_level

net_table = extract_electrode_nets('PD_ElectrodeBoard_v7.kicad_pcb')

print(net_table)

pin_table = {}
for refdes, net_name in net_table.items():
    match = re.match('/P(\d+)', net_name)
    if match is None:
        print(f"Failed to match pin number from net '{net_name}'")
    else:
        pin = int(match.group(1))
        pin_table[refdes] = pin

layout = {}

# Create empty
def create_grid_dict(grid: Grid):
    ret = {}
    ret['origin'] = grid.origin
    ret['pitch'] = grid.pitch
    ret['pins'] = [[None] * grid.width for _ in range(grid.height)]
    for pos, electrode in grid.electrodes.items():
        ret['pins'][pos[1]][pos[0]] = pin_table[f'E{electrode.refdes}']
    return ret

def create_periph_dict(periph: Peripheral):
    return {
        'class': periph.peripheral_class,
        'type': periph.peripheral_type,
        'id': periph.id,
        'origin': periph.global_origin(),
        'rotation': np.rad2deg(periph.rotation),
        'electrodes': [
            {
                'id': e['id'],
                'pin': pin_table[f"E{e['electrode'].refdes}"],
                'polygon': e['electrode'].points,
                'origin': e['electrode'].origin,
            }
            for e in periph.electrodes
        ],
    }

grid_dicts = [create_grid_dict(g) for g in board.grids]
periphs = [create_periph_dict(p) for p in board.peripherals]
layout = {
    "layout": {
        'grids': grid_dicts,
        'peripherals': periphs,
    }
}

with open('electrode_board_layout.json', 'w') as f:
    f.write(json.dumps(layout, cls=CompactJSONEncoder))

print("Wrote layout JSON to `electrode_board_layout.json`")



# %%
