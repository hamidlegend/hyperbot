"""
Colorful console output utilities
"""
import os
import sys

# Enable ANSI colors on Windows
if sys.platform == 'win32':
    os.system('color')
    # Also try to enable VT100 mode
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except:
        pass


# ANSI Color Codes
class Colors:
    # Basic colors
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'

    # Text colors
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'

    # Bright colors
    BRIGHT_RED = '\033[91m'
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_BLUE = '\033[94m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_CYAN = '\033[96m'
    BRIGHT_WHITE = '\033[97m'

    # Background colors
    BG_RED = '\033[41m'
    BG_GREEN = '\033[42m'
    BG_YELLOW = '\033[43m'
    BG_BLUE = '\033[44m'


def colorize(text: str, color: str) -> str:
    """Add color to text"""
    return f"{color}{text}{Colors.RESET}"


def success(text: str) -> str:
    """Green success text"""
    return colorize(text, Colors.BRIGHT_GREEN)


def error(text: str) -> str:
    """Red error text"""
    return colorize(text, Colors.BRIGHT_RED)


def warning(text: str) -> str:
    """Yellow warning text"""
    return colorize(text, Colors.BRIGHT_YELLOW)


def info(text: str) -> str:
    """Cyan info text"""
    return colorize(text, Colors.BRIGHT_CYAN)


def highlight(text: str) -> str:
    """Magenta highlighted text"""
    return colorize(text, Colors.BRIGHT_MAGENTA)


def bold(text: str) -> str:
    """Bold text"""
    return colorize(text, Colors.BOLD)


def dim(text: str) -> str:
    """Dim text"""
    return colorize(text, Colors.DIM)


def price(value: float) -> str:
    """Format price with color"""
    return colorize(f"${value:.4f}", Colors.BRIGHT_CYAN)


def percent(value: float, show_sign: bool = True) -> str:
    """Format percentage with color based on value"""
    if value > 0:
        sign = "+" if show_sign else ""
        return colorize(f"{sign}{value:.2f}%", Colors.BRIGHT_GREEN)
    elif value < 0:
        return colorize(f"{value:.2f}%", Colors.BRIGHT_RED)
    else:
        return colorize(f"{value:.2f}%", Colors.WHITE)


def status_ok(text: str = "OK") -> str:
    """Green OK status"""
    return colorize(f"[✓] {text}", Colors.BRIGHT_GREEN)


def status_fail(text: str = "FAIL") -> str:
    """Red FAIL status"""
    return colorize(f"[✗] {text}", Colors.BRIGHT_RED)


def status_warn(text: str = "WARN") -> str:
    """Yellow WARNING status"""
    return colorize(f"[!] {text}", Colors.BRIGHT_YELLOW)


def status_info(text: str = "INFO") -> str:
    """Cyan INFO status"""
    return colorize(f"[i] {text}", Colors.BRIGHT_CYAN)


def banner(text: str, char: str = "═", width: int = 60) -> str:
    """Create a colored banner"""
    line = char * width
    return f"""{colorize(line, Colors.BRIGHT_CYAN)}
{colorize(text.center(width), Colors.BRIGHT_WHITE + Colors.BOLD)}
{colorize(line, Colors.BRIGHT_CYAN)}"""


def box(lines: list, title: str = None) -> str:
    """Create a colored box with content"""
    width = max(len(line) for line in lines) + 4
    if title:
        width = max(width, len(title) + 4)

    top = colorize("┌" + "─" * (width - 2) + "┐", Colors.CYAN)
    bottom = colorize("└" + "─" * (width - 2) + "┘", Colors.CYAN)

    result = [top]

    if title:
        title_line = colorize("│", Colors.CYAN) + colorize(f" {title}".ljust(width - 2), Colors.BRIGHT_WHITE + Colors.BOLD) + colorize("│", Colors.CYAN)
        separator = colorize("├" + "─" * (width - 2) + "┤", Colors.CYAN)
        result.append(title_line)
        result.append(separator)

    for line in lines:
        content = colorize("│", Colors.CYAN) + f" {line}".ljust(width - 2) + colorize("│", Colors.CYAN)
        result.append(content)

    result.append(bottom)
    return "\n".join(result)


# Trading specific formatting
def long_signal() -> str:
    """Long signal indicator"""
    return colorize("▲ LONG", Colors.BRIGHT_GREEN + Colors.BOLD)


def short_signal() -> str:
    """Short signal indicator"""
    return colorize("▼ SHORT", Colors.BRIGHT_RED + Colors.BOLD)


def breakout_alert() -> str:
    """Breakout alert banner"""
    return colorize("""
╔══════════════════════════════════════════════════════════╗
║  🚀  B R E A K O U T   D E T E C T E D  🚀              ║
╚══════════════════════════════════════════════════════════╝""", Colors.BRIGHT_GREEN + Colors.BOLD)


def trade_executed() -> str:
    """Trade executed banner"""
    return colorize("""
╔══════════════════════════════════════════════════════════╗
║  ✓  T R A D E   E X E C U T E D                         ║
╚══════════════════════════════════════════════════════════╝""", Colors.BRIGHT_CYAN + Colors.BOLD)


def stop_loss_hit() -> str:
    """Stop loss hit banner"""
    return colorize("""
╔══════════════════════════════════════════════════════════╗
║  ✗  S T O P   L O S S   H I T                           ║
╚══════════════════════════════════════════════════════════╝""", Colors.BRIGHT_RED + Colors.BOLD)


def take_profit_hit() -> str:
    """Take profit hit banner"""
    return colorize("""
╔══════════════════════════════════════════════════════════╗
║  ★  T A K E   P R O F I T   H I T                       ║
╚══════════════════════════════════════════════════════════╝""", Colors.BRIGHT_GREEN + Colors.BOLD)


def monitoring(timeframe: str, tl_price: float, current: float, distance: float) -> str:
    """Format monitoring status"""
    tf_color = Colors.BRIGHT_YELLOW if timeframe == "1m" else Colors.BRIGHT_BLUE

    dist_str = percent(distance, show_sign=True)

    return (
        f"{colorize(f'[{timeframe}]', tf_color)} "
        f"Monitoring │ "
        f"TL: {price(tl_price)} │ "
        f"Price: {price(current)} │ "
        f"Distance: {dist_str}"
    )
