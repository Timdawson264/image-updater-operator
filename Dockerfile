FROM alpine

RUN apk add -u python3 py3-pip tini skopeo && pip install --upgrade kubernetes docker-registry-client

ADD operator.py /

ENTRYPOINT ["/sbin/tini", "-g", "--"]
CMD python3 /operator.py
