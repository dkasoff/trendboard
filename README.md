# Trendboard.fyi

Trendboard.fyi is a dynamic trend scoring engine that analyzes product trends using Google Trends data and estimated signals from social media platforms like TikTok, Instagram, and Reddit. It provides a comprehensive scoring system to identify emerging trends, high-flyers, and cooling products across various categories.

## Features

- **Google Trends Integration**: Fetches real-time interest data for product keywords over the past 3 months.
- **Multi-Signal Scoring**: Combines velocity (growth rate), density (community spread), sentiment, and conversion signals.
- **Product Categories**: Supports categories like Sleep & Recovery, Wellness, Skincare, Jewelry, Beauty & Grooming, and Audio.
- **Web Dashboard**: Interactive HTML dashboard with charts and trend visualizations.
- **Weekly Scoring**: Runs automated scoring to rank products and identify trend states (NEW_ENTRY, HIGH_FLYER, TRENDING, COOLING, FALLING_STAR, STAPLE, BELOW_THRESHOLD).

## Architecture

The core scoring formula is:
```
TS = (0.22 * Velocity) + (0.28 * Density) + (0.18 * Sentiment) + (0.32 * Conversion)
```

- **Velocity**: Volume-weighted Google Trends week-over-week growth.
- **Density**: Creator-tier-weighted community spread across platforms.
- **Sentiment**: Product and category sentiment analysis.
- **Conversion**: Purchase intent signals from social media.

## Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd trendboard
   ```

2. Install dependencies:
   ```bash
   pip install pytrends
   ```

   Note: Ensure Python 3.7+ is installed.

## Usage

### Running the Pipeline

Execute the main pipeline to fetch trends and generate scores:

```bash
python pipeline_v1.py
```

This will:
- Fetch Google Trends data for predefined products.
- Estimate signals from TikTok, Instagram, and Reddit.
- Run weekly scoring and display ranked results.

### Running Tests

Run the scorer tests:

```bash
python test_scorer.py
```

Run live Google Trends test:

```bash
python live_test.py
```

### Viewing the Dashboard

Open `trendboard.html` or `index.html` in a web browser to view the interactive dashboard.

## Project Structure

- `pipeline_v1.py`: Main pipeline script for fetching data and running scoring.
- `scorer.py`: Scoring engine with signal classes and scoring logic.
- `test_scorer.py`: Unit tests for the scorer module.
- `live_test.py`: Test script for Google Trends fetching.
- `google_trends_test.py`: Additional Google Trends tests.
- `trendboard.html`: Main dashboard HTML file.
- `index.html`: Alternative dashboard HTML file.

## Dependencies

- `pytrends`: For Google Trends API access.
- `dataclasses`, `math`, `datetime`: Standard Python libraries.

## Contributing

Contributions are welcome. Please ensure tests pass before submitting pull requests.

## License

[Add license information here]