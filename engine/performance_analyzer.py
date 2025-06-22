# quantitative_momentum_trader/engine/performance_analyzer.py
"""
Performance Analyzer for the Quantitative Momentum Trading System.

This module provides tools for visualizing trading performance. It leverages
the existing plotting utilities to create charts like equity curves.
"""

import logging
import pandas as pd
import tkinter as tk
from typing import Optional


# Import the existing plotting utility from the project structure
from utils import plotting_utils

logger = logging.getLogger(__name__)

class PerformanceAnalyzer:
    """
    Analyzes and visualizes portfolio performance over time.
    """
    def __init__(self):
        """
        Initializes the PerformanceAnalyzer.
        """
        logger.info("PerformanceAnalyzer initialized.")

    def plot_equity_curve(
        self,
        equity_series: pd.Series,
        strategy_name: str,
        target_tk_frame: Optional['tk.Frame'] = None
    ) -> None:
        """
        Plots an equity curve using the provided plotting utility.

        This is a conceptual implementation showing how one would integrate with
        the `plotting_utils` module. It adapts a P&L plotting function for the
        purpose of showing an equity curve.

        Args:
            equity_series (pd.Series): A pandas Series with a DatetimeIndex and
                                       portfolio values.
            strategy_name (str): The name of the strategy for the plot title.
            target_tk_frame (Optional[tk.Frame]): A Tkinter frame to embed the plot in.
                                                  If None, the plot will be displayed in a
                                                  new window (default matplotlib behavior).
        """
        if equity_series.empty:
            logger.warning("Cannot plot equity curve: The equity series is empty.")
            return

        logger.info(f"Generating equity curve plot for strategy: {strategy_name}")

        # --- Adapt data for the plotting function ---
        # The plotting_utils function is designed for P&L profiles (P&L vs. Stock Price).
        # We can creatively reuse it for an equity curve (Value vs. Time).
        
        # Let's create a mock `strategy_details` dictionary.
        # We will map our time series data to its expected keys.
        strategy_details = {
            "s_values_for_plot": equity_series.index,  # X-axis: Time
            "pnl_values_for_plot": equity_series.values, # Y-axis: Portfolio Value
            "description": f"{strategy_name} Equity Curve",
            "max_profit": equity_series.max(),
            "total_initial_cost": -equity_series.min() # Mocking max loss as min value
        }
        
        # --- Parameters for the plotting function ---
        ticker_symbol = "Portfolio"
        current_price = equity_series.index[-1] # Mock current 'price' as the last date
        
        try:
            if target_tk_frame:
                # Use the provided utility to plot within a Tkinter frame
                plotting_utils.plot_combined_pnl_chart_tkinter(
                    target_tk_frame=target_tk_frame,
                    strategy_details=strategy_details,
                    ticker_symbol=ticker_symbol,
                    current_price=current_price, # This will be a timestamp, annotation might be odd
                    lower_2_sigma_target=None,
                    upper_2_sigma_target=None,
                    currency="$"
                )
                logger.info("Equity curve embedded in Tkinter frame.")
            else:
                # If no Tkinter frame is provided, we can't use the specific util function.
                # A more general plotting function would be needed in plotting_utils.py.
                # For now, we log a message.
                logger.warning("No Tkinter frame provided. Standalone plotting not implemented with this utility.")
                # A future implementation in plotting_utils could be:
                # plotting_utils.display_standalone_plot(...)

        except Exception as e:
            logger.error(f"An error occurred while plotting the equity curve: {e}", exc_info=True)