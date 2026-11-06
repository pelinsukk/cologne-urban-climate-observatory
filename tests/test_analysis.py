from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from analyze import SURFACES, paired_hours, read_weather, summarize


class AnalysisTest(unittest.TestCase):
    def test_pairing_requires_every_box_and_preserves_difference_direction(self):
        time = pd.date_range("2021-06-07", periods=24, freq="5min")
        values = {name: pd.Series(20., index=time) for name in SURFACES.values()}
        values["tar"] += 2
        values["grass"] = values["grass"].drop(time[12:15])
        paired = paired_hours(values, 10)
        self.assertEqual(paired.index.tolist(), [time[0]])
        self.assertEqual(summarize(paired)["grass"]["mean_c"], 2.0)

    def test_weather_units_row_is_removed_and_timestamps_are_utc(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "weather.csv"
            path.write_text("date_end,airtemp\nNA,°C\n2021-06-07 00:05:00 UTC,12.5\n")
            weather = read_weather(path)
            self.assertEqual(len(weather), 1)
            self.assertEqual(weather.index[0], pd.Timestamp("2021-06-07 00:05:00Z"))
            self.assertEqual(weather["airtemp"].iloc[0], 12.5)
