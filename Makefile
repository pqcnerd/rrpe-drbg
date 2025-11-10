.PHONY: clean
clean:
	@rm -rf outputs/daily
	@if [ -f outputs/entropy_log.csv ]; then \
		echo "clearing entropy_log.csv"; \
		head -n 1 outputs/entropy_log.csv > outputs/entropy_log.csv.tmp && \
		mv outputs/entropy_log.csv.tmp outputs/entropy_log.csv; \
	else \
		echo "entropy_log.csv does not exist, creating with header..."; \
		mkdir -p outputs; \
		echo "date,symbol,prediction,outcome,symbol_bits,commit,context,salt,close_prev,close_today,provider,tie,p_commit,p_reveal,commit_bar_ts_et,delta,sign_bit,mag_q,symbol_bytes_hex" > outputs/entropy_log.csv; \
	fi
