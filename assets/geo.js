// SPDX-License-Identifier: MIT
// Viewer location without any network request: the country is inferred from the
// browser time zone; an optional precise position is matched to the nearest city
// in the list below, locally. Country names follow the data (USA, UK, South Korea...).

export const TZ_COUNTRY = {
  "Asia/Ho_Chi_Minh": "Vietnam", "Asia/Saigon": "Vietnam", "Asia/Hanoi": "Vietnam",
  "Asia/Bangkok": "Thailand", "Asia/Vientiane": "Laos", "Asia/Phnom_Penh": "Cambodia", "Asia/Yangon": "Myanmar",
  "Asia/Singapore": "Singapore", "Asia/Kuala_Lumpur": "Malaysia", "Asia/Jakarta": "Indonesia", "Asia/Makassar": "Indonesia",
  "Asia/Manila": "Philippines", "Asia/Shanghai": "China", "Asia/Chongqing": "China", "Asia/Urumqi": "China",
  "Asia/Hong_Kong": "Hong Kong", "Asia/Macau": "Macau", "Asia/Taipei": "Taiwan", "Asia/Tokyo": "Japan",
  "Asia/Seoul": "South Korea", "Asia/Kolkata": "India", "Asia/Calcutta": "India", "Asia/Dhaka": "Bangladesh",
  "Asia/Karachi": "Pakistan", "Asia/Kathmandu": "Nepal", "Asia/Colombo": "Sri Lanka", "Asia/Dubai": "UAE",
  "Asia/Riyadh": "Saudi Arabia", "Asia/Qatar": "Qatar", "Asia/Tehran": "Iran", "Asia/Jerusalem": "Israel",
  "Asia/Tel_Aviv": "Israel", "Asia/Almaty": "Kazakhstan", "Asia/Tashkent": "Uzbekistan", "Europe/Istanbul": "Turkey",
  "Australia/Sydney": "Australia", "Australia/Melbourne": "Australia", "Australia/Brisbane": "Australia",
  "Australia/Perth": "Australia", "Australia/Adelaide": "Australia", "Australia/Hobart": "Australia",
  "Pacific/Auckland": "New Zealand", "Europe/London": "UK", "Europe/Dublin": "Ireland", "Europe/Paris": "France",
  "Europe/Berlin": "Germany", "Europe/Madrid": "Spain", "Europe/Lisbon": "Portugal", "Europe/Rome": "Italy",
  "Europe/Amsterdam": "Netherlands", "Europe/Brussels": "Belgium", "Europe/Zurich": "Switzerland",
  "Europe/Vienna": "Austria", "Europe/Prague": "Czech Republic", "Europe/Warsaw": "Poland", "Europe/Budapest": "Hungary",
  "Europe/Stockholm": "Sweden", "Europe/Oslo": "Norway", "Europe/Copenhagen": "Denmark", "Europe/Helsinki": "Finland",
  "Europe/Athens": "Greece", "Europe/Bucharest": "Romania", "Europe/Sofia": "Bulgaria", "Europe/Kiev": "Ukraine",
  "Europe/Kyiv": "Ukraine", "Europe/Moscow": "Russia", "Europe/Luxembourg": "Luxembourg", "Europe/Bratislava": "Slovakia",
  "Europe/Ljubljana": "Slovenia", "Europe/Zagreb": "Croatia", "Europe/Belgrade": "Serbia", "Europe/Tallinn": "Estonia",
  "Europe/Riga": "Latvia", "Europe/Vilnius": "Lithuania", "Atlantic/Reykjavik": "Iceland", "Europe/Malta": "Malta",
  "America/New_York": "USA", "America/Chicago": "USA", "America/Denver": "USA", "America/Los_Angeles": "USA",
  "America/Phoenix": "USA", "America/Anchorage": "USA", "Pacific/Honolulu": "USA", "America/Detroit": "USA",
  "America/Toronto": "Canada", "America/Vancouver": "Canada", "America/Montreal": "Canada", "America/Edmonton": "Canada",
  "America/Halifax": "Canada", "America/Winnipeg": "Canada", "America/Mexico_City": "Mexico", "America/Sao_Paulo": "Brazil",
  "America/Argentina/Buenos_Aires": "Argentina", "America/Buenos_Aires": "Argentina", "America/Santiago": "Chile",
  "America/Bogota": "Colombia", "America/Lima": "Peru", "Africa/Cairo": "Egypt", "Africa/Johannesburg": "South Africa",
  "Africa/Lagos": "Nigeria", "Africa/Nairobi": "Kenya", "Africa/Casablanca": "Morocco", "Africa/Tunis": "Tunisia",
};

// Cities for the nearest-city lookup and for the city list of the viewer's country.
// [name, country, latitude, longitude]
export const CITIES = [
  ["Hanoi", "Vietnam", 21.03, 105.85], ["Ho Chi Minh City", "Vietnam", 10.78, 106.70], ["Da Nang", "Vietnam", 16.05, 108.20],
  ["Hai Phong", "Vietnam", 20.86, 106.68], ["Can Tho", "Vietnam", 10.03, 105.78], ["Hue", "Vietnam", 16.46, 107.59],
  ["Nha Trang", "Vietnam", 12.24, 109.19], ["Quy Nhon", "Vietnam", 13.78, 109.22], ["Da Lat", "Vietnam", 11.94, 108.44],
  ["Vung Tau", "Vietnam", 10.35, 107.08], ["Ha Long", "Vietnam", 20.95, 107.08], ["Vinh", "Vietnam", 18.68, 105.68],
  ["Thai Nguyen", "Vietnam", 21.59, 105.85], ["Buon Ma Thuot", "Vietnam", 12.67, 108.04], ["Phu Quoc", "Vietnam", 10.29, 103.98],
  ["Hoi An", "Vietnam", 15.88, 108.33], ["Quang Ninh", "Vietnam", 21.01, 107.29], ["Bien Hoa", "Vietnam", 10.95, 106.82],
  ["Thu Duc", "Vietnam", 10.85, 106.77], ["Nam Dinh", "Vietnam", 20.43, 106.17], ["Thanh Hoa", "Vietnam", 19.81, 105.78],
  ["Long Xuyen", "Vietnam", 10.39, 105.44], ["Rach Gia", "Vietnam", 10.01, 105.08], ["Pleiku", "Vietnam", 13.98, 108.00],
  ["Bangkok", "Thailand", 13.76, 100.50], ["Singapore", "Singapore", 1.35, 103.82], ["Kuala Lumpur", "Malaysia", 3.14, 101.69],
  ["Jakarta", "Indonesia", -6.21, 106.85], ["Bali", "Indonesia", -8.65, 115.22], ["Manila", "Philippines", 14.60, 120.98],
  ["Beijing", "China", 39.90, 116.40], ["Shanghai", "China", 31.23, 121.47], ["Shenzhen", "China", 22.54, 114.06],
  ["Guangzhou", "China", 23.13, 113.26], ["Hangzhou", "China", 30.27, 120.16], ["Chengdu", "China", 30.57, 104.07],
  ["Xi'an", "China", 34.34, 108.94], ["Wuhan", "China", 30.59, 114.31], ["Nanjing", "China", 32.06, 118.80],
  ["Hong Kong", "Hong Kong", 22.32, 114.17], ["Macau", "Macau", 22.20, 113.54], ["Taipei", "Taiwan", 25.03, 121.57],
  ["Tokyo", "Japan", 35.68, 139.69], ["Kyoto", "Japan", 35.01, 135.77], ["Osaka", "Japan", 34.69, 135.50],
  ["Seoul", "South Korea", 37.57, 126.98], ["Busan", "South Korea", 35.18, 129.08], ["Delhi", "India", 28.61, 77.21],
  ["Bangalore", "India", 12.97, 77.59], ["Mumbai", "India", 19.08, 72.88], ["Dubai", "UAE", 25.20, 55.27],
  ["Abu Dhabi", "UAE", 24.45, 54.38], ["Sydney", "Australia", -33.87, 151.21], ["Melbourne", "Australia", -37.81, 144.96],
  ["Brisbane", "Australia", -27.47, 153.03], ["Perth", "Australia", -31.95, 115.86], ["Adelaide", "Australia", -34.93, 138.60],
  ["Auckland", "New Zealand", -36.85, 174.76], ["London", "UK", 51.51, -0.13], ["Edinburgh", "UK", 55.95, -3.19],
  ["Paris", "France", 48.86, 2.35], ["Lyon", "France", 45.76, 4.84], ["Berlin", "Germany", 52.52, 13.40],
  ["Munich", "Germany", 48.14, 11.58], ["Madrid", "Spain", 40.42, -3.70], ["Barcelona", "Spain", 41.39, 2.17],
  ["Lisbon", "Portugal", 38.72, -9.14], ["Rome", "Italy", 41.90, 12.50], ["Milan", "Italy", 45.46, 9.19],
  ["Amsterdam", "Netherlands", 52.37, 4.90], ["Brussels", "Belgium", 50.85, 4.35], ["Zurich", "Switzerland", 47.38, 8.54],
  ["Geneva", "Switzerland", 46.20, 6.14], ["Vienna", "Austria", 48.21, 16.37], ["Prague", "Czech Republic", 50.08, 14.44],
  ["Stockholm", "Sweden", 59.33, 18.07], ["Copenhagen", "Denmark", 55.68, 12.57], ["Helsinki", "Finland", 60.17, 24.94],
  ["Oslo", "Norway", 59.91, 10.75], ["Athens", "Greece", 37.98, 23.73], ["Istanbul", "Turkey", 41.01, 28.98],
  ["New York", "USA", 40.71, -74.01], ["Boston", "USA", 42.36, -71.06], ["Washington", "USA", 38.91, -77.04],
  ["Chicago", "USA", 41.88, -87.63], ["San Francisco", "USA", 37.77, -122.42], ["Los Angeles", "USA", 34.05, -118.24],
  ["Seattle", "USA", 47.61, -122.33], ["San Diego", "USA", 32.72, -117.16], ["Toronto", "Canada", 43.65, -79.38],
  ["Vancouver", "Canada", 49.28, -123.12], ["Montreal", "Canada", 45.50, -73.57], ["Mexico City", "Mexico", 19.43, -99.13],
  ["Sao Paulo", "Brazil", -23.55, -46.63], ["Rio de Janeiro", "Brazil", -22.91, -43.17], ["Cairo", "Egypt", 30.04, 31.24],
  ["Cape Town", "South Africa", -33.92, 18.42], ["Nairobi", "Kenya", -1.29, 36.82],
];

export function countryFromTimeZone(tz) {
  return TZ_COUNTRY[tz] || "";
}

export function browserTimeZone() {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch { return ""; }
}

/** Great-circle distance in kilometres. */
export function distanceKm(lat1, lon1, lat2, lon2) {
  const r = (d) => (d * Math.PI) / 180;
  const a = Math.sin(r(lat2 - lat1) / 2) ** 2 + Math.cos(r(lat1)) * Math.cos(r(lat2)) * Math.sin(r(lon2 - lon1) / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(a));
}

/** Nearest listed city, or null when nothing lies within maxKm. */
export function nearestCity(lat, lon, maxKm = 300) {
  let best = null;
  for (const [name, country, la, lo] of CITIES) {
    const d = distanceKm(lat, lon, la, lo);
    if (!best || d < best.km) best = { name, country, km: d };
  }
  return best && best.km <= maxKm ? best : null;
}

export function citiesOf(country) {
  return CITIES.filter((c) => c[1] === country).map((c) => c[0]);
}
