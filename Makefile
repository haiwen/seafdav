all: seaf-dav.tar.gz

seaf-dav.tar.gz:
	cd .. && \
	tar czvf $@ seaf-dav/ \
	--exclude='*.git*' \
	--exclude='*.log' \
	--exclude='*~' \
	--exclude='*#' \
	--exclude='*.gz' \
	--exclude='*.pyc' \
	--exclude='build/*' \
	--exclude='dist/*' \
	--exclude='Makefile' \
	--exclude='.pydevproject' \
	--exclude='.project' \
	--exclude-vcs && \
	mv $@ seaf-dav/

clean:
	rm -f seaf-dav.tar.gz