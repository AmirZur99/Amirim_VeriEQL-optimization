FROM yanghece96/verieql
WORKDIR /VeriEQL
COPY . /VeriEQL
RUN pip install -r requirements.txt