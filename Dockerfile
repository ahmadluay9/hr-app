# Dockerfile

# 1. Use an official Python runtime as a parent image
FROM python:3.12-slim

# 2. Set the working directory inside the container
WORKDIR /code

# 3. Copy the dependencies file and install them
# This is done first to leverage Docker's layer caching
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# 4. Copy the application code into the container
COPY ./main.py /code/main.py

# 5. Command to run the application
# Hugging Face Spaces exposes port 7860. We must bind our app to this port.
# The host '0.0.0.0' makes the app accessible from outside the container.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]