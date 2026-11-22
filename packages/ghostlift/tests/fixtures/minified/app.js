function clamp(value, low, high) {
  if (value < low) {
    return low;
  }
  if (value > high) {
    return high;
  }
  return value;
}

function describeScore(score) {
  const label = score >= 90 ? "high" : "low";
  return "score is " + label;
}

const doubleIt = (number) => {
  return number * 2;
};
