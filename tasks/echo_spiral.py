"""Short chords of an outward spiral; inspect for absorption between chords."""
from math import ceil


def echo_spiral_steps():
    arc = 0
    while True:
        # Equal yaw per arc, growing travel per arc => growing turning radius.
        # Split longer arcs so no forward command hides the prompt for >220ms.
        duration = 180+12*arc
        parts = ceil(duration/220)
        for index in range(parts):
            yaw = round(-84*(index+1)/parts)-round(-84*index/parts)
            walk = round(duration*(index+1)/parts)-round(duration*index/parts)
            yield yaw, walk
        arc += 1
