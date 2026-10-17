// 6-channel EMG reader (crosstalk-fixed)
// Each pin is read twice: the first dummy read lets the ADC settle,
// removing crosstalk between analog channels.
// Serial at 115200 baud for a higher sample rate.
int analogInput[6] = {A0, A1, A2, A3, A4, A5};
int value[6];

void setup()
{
  Serial.begin(115200);
}

void loop()
{
  for (int i = 0; i < 6; i++)
  {
    analogRead(analogInput[i]);          // dummy read: charge the sample-and-hold capacitor
    delayMicroseconds(50);
    value[i] = analogRead(analogInput[i]);
  }
  for (int i = 0; i < 5; i++)
  {
    Serial.print(value[i]);
    Serial.print(",");
  }
  Serial.println(value[5]);
  delay(2);
}
