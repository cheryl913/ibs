import random
import datetime

def generate_transaction_data():
  """Generates 50 rows of sample data for transaction_data.csv."""
  data = []
  for i in range(50):
    timestamp = random.randint(1546300800, 1646300800)
    amount = round(random.uniform(10.01, 5000.99), 2)
    transaction_type = "online_transfer"
    customer_id = random.randint(1, 100)
    merchant = "IBS"
    location = random.choice(['Johor','Melaka','Selangor','Kuala Lumpur','Perak','Negeri Sembilan','Pulau Penang','Kedah','Perlis','Kelantan','Terengganu','Pahang','Sarawak','Sabah'])
    transaction_status = "Successful"
    fraud_label = "0"
    data.append((
        i,
        amount,
        datetime.datetime.fromtimestamp(timestamp),
        transaction_type,
        customer_id,
        merchant,
        location,
        transaction_status,
        fraud_label,
    ))
  return data

if __name__ == "__main__":
  data = generate_transaction_data()
  with open("transaction_data.csv", "w") as f:
    f.write("Transaction ID,Transaction Amount,Transaction Date,Transaction Type,Customer ID,Merchant,Location,Transaction Status,Fraud Label\n")
    for row in data:
      f.write(",".join([str(item) for item in row]) + "\n")