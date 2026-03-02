import tkinter as tk

from app.ui import ExifOverlayApp


def main() -> None:
    root = tk.Tk()
    ExifOverlayApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
