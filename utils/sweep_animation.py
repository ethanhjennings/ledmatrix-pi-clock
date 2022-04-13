import time
from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics

class SweepAnimation:
    def __init__(self):
        self.matrix = RGBMatrix(options = self.get_options())
        self.offscreen_canvas = self.matrix.CreateFrameCanvas()
        self.y_pos = 0
        self.heat_level = [0]*self.offscreen_canvas.height
        
    def get_options(self):
        options = RGBMatrixOptions()
        options.rows = 32
        options.cols = 64
        options.gpio_slowdown = 4
        return options

    def draw_loop(self):
        start = time.time()
        canvas = self.offscreen_canvas
        canvas.Fill(0, 0, 0)

        for y in range(canvas.height):
            self.heat_level[y] -= 0.02
            self.heat_level[y] = max(self.heat_level[y], 0)
            graphics.DrawLine(canvas, 0, y, canvas.width-1, y, graphics.Color(0, int(self.heat_level[y]*100), int(self.heat_level[y]*255)))
        graphics.DrawLine(canvas, 0, self.y_pos, canvas.width-1, self.y_pos, graphics.Color(0, 255, 255))

        if (self.y_pos <= canvas.height):
            self.heat_level[int(self.y_pos)] = 1.0


        self.y_pos = (self.y_pos + 0.2) % (canvas.height + 5)
        self.offscreen_canvas = self.matrix.SwapOnVSync(self.offscreen_canvas)

    def run(self):
        try:
            # Start loop
            print("Press CTRL-C to stop")
            while True:
                self.draw_loop()
        except KeyboardInterrupt:
            print("Exiting\n")
            sys.exit(0)

if __name__ == "__main__":
    anim = SweepAnimation()
    anim.run()
