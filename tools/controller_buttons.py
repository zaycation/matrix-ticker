"""Show what each controller button sends, to pick one for the counter.

    pip install pygame
    python tools/controller_buttons.py

Press each button you're curious about (G1, G5, mute, PS, paddles...) one at a time and
note the line it prints. A button that prints nothing isn't visible to apps as-is.
Works while other windows (even a game) have focus. Ctrl+C to stop.
"""
import os
import time

os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")   # keep reading when not focused
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

try:
    import pygame
except ImportError:
    raise SystemExit("Needs pygame:  pip install pygame")


def main():
    pygame.init()
    pygame.joystick.init()
    sticks = {}
    print("Waiting for a controller... (plug it in or turn it on)")
    last_axes = {}
    try:
        while True:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:          # pygame turns Ctrl+C into this
                    return
                if ev.type == pygame.JOYDEVICEADDED:
                    js = pygame.joystick.Joystick(ev.device_index)
                    sticks[js.get_instance_id()] = js
                    print(f"Connected: {js.get_name()}  ({js.get_numbuttons()} buttons, "
                          f"{js.get_numhats()} d-pads, {js.get_numaxes()} sticks/triggers)")
                    print("Press buttons now.")
                elif ev.type == pygame.JOYDEVICEREMOVED:
                    sticks.pop(ev.instance_id, None)
                    print("Controller disconnected.")
                elif ev.type == pygame.JOYBUTTONDOWN:
                    print(f"  button {ev.button} pressed")
                elif ev.type == pygame.JOYBUTTONUP:
                    print(f"  button {ev.button} released")
                elif ev.type == pygame.JOYHATMOTION and ev.value != (0, 0):
                    print(f"  d-pad {ev.hat}: {ev.value}")
                elif ev.type == pygame.JOYAXISMOTION:
                    # only report big moves, so resting sticks don't flood the screen
                    big = abs(ev.value) > 0.8
                    if big != last_axes.get(ev.axis, False):
                        last_axes[ev.axis] = big
                        if big:
                            print(f"  stick/trigger axis {ev.axis} pushed")
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
