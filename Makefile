all: seafdav.tar.gz

seafdav.tar.gz:
	git archive HEAD | gzip > seafdav.tar.gz
clean:
	rm -f *.gz
