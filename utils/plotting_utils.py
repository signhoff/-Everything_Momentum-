# utils/plotting_utils.py
# This file contains functions for plotting strategy P&L charts,
# specifically designed for embedding within a Tkinter GUI.

import matplotlib
matplotlib.use('TkAgg') # Ensure Matplotlib uses the Tkinter backend
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import numpy as np
import tkinter as tk # For type hinting (tk.Frame)
from typing import Dict, List, Any, Optional

# Module-level variables to keep track of the current canvas and toolbar
# This helps in managing and clearing previous plots if the function is called multiple times
# on the same target_tk_frame.
_figure_canvas_agg: Optional[FigureCanvasTkAgg] = None
_toolbar: Optional[NavigationToolbar2Tk] = None

def plot_combined_pnl_chart_tkinter(
    target_tk_frame: tk.Frame,
    strategy_details: Dict[str, Any],
    ticker_symbol: str,
    current_price: float,
    lower_2_sigma_target: Optional[float],
    upper_2_sigma_target: Optional[float],
    currency: str = "$"
) -> None:
    """
    Plots the P&L curve for a given options strategy and embeds it into a Tkinter Frame.

    The function clears any previous plot from the target_tk_frame before drawing a new one.
    It visualizes the P&L, breakeven points, max profit/loss, current price, and optional
    2-sigma price targets.

    Args:
        target_tk_frame (tk.Frame): The Tkinter Frame widget where the plot will be embedded.
        strategy_details (Dict[str, Any]): A dictionary containing all necessary details
            of the strategy to be plotted. Expected keys include:
            - "s_values_for_plot" (List[float] or np.ndarray): Stock prices for the x-axis.
            - "pnl_values_for_plot" (List[float] or np.ndarray): P&L values for the y-axis.
            - "total_initial_cost" (float, optional): The net initial cost of the spread 
              (positive for debit, negative for credit), representing max loss for debit spreads if positive.
            -  representing max loss for debit spreads.
            - "lower_breakeven" (float, optional): The lower breakeven stock price.
            - "upper_breakeven" (float, optional): The upper breakeven stock price.
            - "max_profit" (float, optional): The maximum profit achievable by the strategy.
            - "max_profit_details_for_plot" (Dict, optional): Contains {'price': S, 'profit': P}
              for marking the exact point of max profit.
            - "description" (str, optional): A short description of the strategy for the title.
            - "front_exp" (str, optional): Front month expiration date (YYYYMMDD).
            - "back_exp" (str, optional): Back month expiration date (YYYYMMDD).
            - "profit_debit_ratio" (float, optional): Profit/Debit ratio.
            - "pnl_at_atm_pin" (float, optional): P&L if stock pins at ATM at front expiry.
            - "covers_lower_2_sigma" (bool, optional): If strategy is profitable at lower 2-sigma.
            - "covers_upper_2_sigma" (bool, optional): If strategy is profitable at upper 2-sigma.
        ticker_symbol (str): The stock ticker symbol (e.g., "AAPL").
        current_price (float): The current market price of the underlying stock.
        lower_2_sigma_target (Optional[float]): The lower 2-sigma price target for the stock.
                                                If None, this line/shading is not plotted.
        upper_2_sigma_target (Optional[float]): The upper 2-sigma price target for the stock.
                                                If None, this line/shading is not plotted.
        currency (str): The currency symbol to use for annotations (e.g., "$").

    Returns:
        None
    """
    global _figure_canvas_agg, _toolbar

    # Clear previous plot, canvas, and toolbar from the target frame
    # This is important if the function is called multiple times to update the plot.
    for widget in target_tk_frame.winfo_children():
        widget.destroy()
    _figure_canvas_agg = None # Reset module-level references
    _toolbar = None

    s_values_raw = strategy_details.get("s_values_for_plot")
    pnl_values_raw = strategy_details.get("pnl_values_for_plot")
    total_initial_cost = strategy_details.get("total_initial_cost", 0.0) # Max loss for debit spreads

    # Validate essential plotting data
    if not isinstance(s_values_raw, (list, np.ndarray)) or \
       not isinstance(pnl_values_raw, (list, np.ndarray)) or \
       len(s_values_raw) == 0 or len(pnl_values_raw) == 0 or \
       len(s_values_raw) != len(pnl_values_raw):
        
        # Display a message in the Tkinter frame if data is missing or invalid
        error_message = "Plotting data (s_values_for_plot or pnl_values_for_plot)\nis missing, empty, or mismatched in length."
        lbl = tk.Label(target_tk_frame, text=error_message, fg="red", justify=tk.LEFT)
        lbl.pack(padx=10, pady=10, anchor=tk.CENTER)
        print(f"Error in plot_combined_pnl_chart_tkinter: {error_message}") # Also log to console
        return

    s_values = np.array(s_values_raw)
    pnl_values = np.array(pnl_values_raw)

    # Create the Matplotlib figure and axes
    # plt.style.use('seaborn-v0_8-darkgrid') # Example of using a style
    fig, ax = plt.subplots(figsize=(8, 5)) # Adjust figsize as needed for embedding

    # Plot P&L curve
    ax.plot(s_values, pnl_values, label="P&L at Front Expiry", color="blue", linewidth=1.5)

    # Zero P&L line (breakeven line)
    ax.axhline(y=0, color='black', linestyle='-', linewidth=0.7)

    # Current stock price
    ax.axvline(x=current_price, color='red', linestyle='--', label=f"Current: {currency}{current_price:.2f}", linewidth=1)

    # Optional 2-sigma price targets and range shading
    if lower_2_sigma_target is not None:
        ax.axvline(x=lower_2_sigma_target, color='darkorange', linestyle=':', label=f"2σ Low: {currency}{lower_2_sigma_target:.2f}", linewidth=1)
    if upper_2_sigma_target is not None:
        ax.axvline(x=upper_2_sigma_target, color='darkorange', linestyle=':', label=f"2σ High: {currency}{upper_2_sigma_target:.2f}", linewidth=1)
    
    if lower_2_sigma_target is not None and upper_2_sigma_target is not None:
        # Ensure lower < upper for axvspan
        low_span = min(lower_2_sigma_target, upper_2_sigma_target)
        high_span = max(lower_2_sigma_target, upper_2_sigma_target)
        ax.axvspan(low_span, high_span, alpha=0.1, color='orange', label="2σ Range") # Changed color for better visibility

    # Breakeven points
    lower_bep = strategy_details.get("lower_breakeven")
    if lower_bep is not None and s_values.min() <= lower_bep <= s_values.max():
        ax.plot(lower_bep, 0, 'x', color='green', markersize=7, markeredgewidth=1.5, label=f"BEP: {currency}{lower_bep:.2f}")

    upper_bep = strategy_details.get("upper_breakeven")
    # Avoid double labeling if only one BEP or if they are too close for separate labels
    bep_label_upper = None
    if upper_bep is not None:
        if lower_bep is None or abs(upper_bep - lower_bep) > 0.01 * current_price: # Only label if distinct
            bep_label_upper = f"BEP: {currency}{upper_bep:.2f}"
        if s_values.min() <= upper_bep <= s_values.max():
            ax.plot(upper_bep, 0, 'x', color='green', markersize=7, markeredgewidth=1.5, label=bep_label_upper)

    # Max Profit point
    max_profit_details = strategy_details.get("max_profit_details_for_plot") # Expected: {'price': S, 'profit': P}
    if max_profit_details and isinstance(max_profit_details, dict) and \
       'price' in max_profit_details and 'profit' in max_profit_details:
        s_at_max_p = max_profit_details['price']
        max_p_val = max_profit_details['profit']
        if s_values.min() <= s_at_max_p <= s_values.max(): # Ensure it's within plot range
             ax.plot(s_at_max_p, max_p_val, 'o', color='purple', markersize=7, label=f"Max Profit: {currency}{max_p_val:.2f}")
    elif strategy_details.get("max_profit") is not None: # Fallback if specific point isn't given but value is
        ax.plot([],[], ' ', label=f"Max Profit (approx): {currency}{strategy_details['max_profit']:.2f}")


    # Max Loss line (typically the negative of total debit for debit spreads)
    if total_initial_cost > 0: # Only plot if it's a debit spread (positive cost)
        ax.axhline(y=-total_initial_cost, color='darkred', linestyle='--', linewidth=0.8, label=f"Max Loss: {currency}{-total_initial_cost:.2f}") # <<< CHANGED

    # Chart labels and title
    strategy_desc = strategy_details.get('description', 'Strategy P&L')
    ax.set_title(f"{ticker_symbol} - {strategy_desc}", fontsize=11)
    ax.set_xlabel(f"Stock Price at Front Expiration ({currency})", fontsize=10)
    ax.set_ylabel(f"Profit / Loss ({currency})", fontsize=10)
    
    # Legend: 'best' can sometimes overlap; consider 'upper left', 'lower left', etc.
    # Or, adjust layout to make space.
    ax.legend(fontsize=8, loc='best') 
    ax.grid(True, which='both', linestyle=':', linewidth=0.5)

    # Improve layout to prevent labels from being cut off
    plt.tight_layout(pad=1.0) # Add some padding

    # Embed the Matplotlib plot in the Tkinter frame
    _figure_canvas_agg = FigureCanvasTkAgg(fig, master=target_tk_frame)
    _figure_canvas_agg.draw()
    canvas_widget = _figure_canvas_agg.get_tk_widget()
    canvas_widget.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

    # Add Matplotlib navigation toolbar
    _toolbar = NavigationToolbar2Tk(_figure_canvas_agg, target_tk_frame)
    _toolbar.update()
    # The toolbar widget is typically packed below the canvas or managed by its own frame.
    # Packing it directly after the canvas might not always be ideal depending on layout.
    # For simplicity here, it's added. A common practice is to pack canvas_widget first,
    # then pack the toolbar widget separately if it needs to be at the bottom of the frame.
    # However, NavigationToolbar2Tk often manages its own placement relative to the canvas.
    # Let's ensure the canvas takes precedence for expansion.
    # canvas_widget.pack(side=tk.TOP, fill=tk.BOTH, expand=True) # Already packed
    # _toolbar.pack(side=tk.BOTTOM, fill=tk.X) # Example: pack toolbar at bottom

    # print("Plot generated and embedded in Tkinter frame.") # For debugging
