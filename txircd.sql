SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0;
SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0;
SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='TRADITIONAL,ALLOW_INVALID_DATES';

CREATE SCHEMA IF NOT EXISTS `txircd` DEFAULT CHARACTER SET utf8 ;
USE `txircd` ;

-- -----------------------------------------------------
-- Table `txircd`.`donors`
-- -----------------------------------------------------
DROP TABLE IF EXISTS `txircd`.`donors` ;

CREATE  TABLE IF NOT EXISTS `txircd`.`donors` (
  `id` INT(10) UNSIGNED NOT NULL AUTO_INCREMENT ,
  `email` VARCHAR(255) NOT NULL ,
  `password` VARCHAR(255) NULL DEFAULT NULL ,
  `display_name` VARCHAR(255) NULL DEFAULT NULL ,
  PRIMARY KEY (`id`) ,
  UNIQUE INDEX `email_UNIQUE` (`email` ASC) )
ENGINE = MyISAM
DEFAULT CHARACTER SET = utf8
COMMENT = 'Donor accounts';

-- -----------------------------------------------------
-- Table `txircd`.`prizes`
-- -----------------------------------------------------
DROP TABLE IF EXISTS `txircd`.`prizes` ;

CREATE  TABLE IF NOT EXISTS `txircd`.`prizes` (
  `id` INT(10) UNSIGNED NULL AUTO_INCREMENT ,
  `name` VARCHAR(255) NOT NULL ,
  `sold` TINYINT(1) UNSIGNED NOT NULL DEFAULT '0' ,
  `starting_bid` DECIMAL(8,2) NOT NULL DEFAULT '0.00' ,
  `sold_amount` DECIMAL(8,2) UNSIGNED NOT NULL DEFAULT '0.00' ,
  `donor_id` INT(10) UNSIGNED NULL ,
  PRIMARY KEY (`id`) )
ENGINE = MyISAM
DEFAULT CHARACTER SET = utf8, 
COMMENT = 'Auction items' ;

CREATE INDEX `name` ON `txircd`.`prizes` (`name` ASC) ;
CREATE INDEX `sold` ON `txircd`.`prizes` (`sold` ASC) ;
CREATE INDEX `donor_id` ON `txircd`.`prizes` (`donor_id` ASC) ;

-- -----------------------------------------------------
-- Table `txircd`.`irc_nicks`
-- -----------------------------------------------------
DROP TABLE IF EXISTS `txircd`.`ircnicks` ;

CREATE  TABLE IF NOT EXISTS `txircd`.`ircnicks` (
  `id` INT(10) UNSIGNED NOT NULL AUTO_INCREMENT ,
  `donor_id` INT(10) UNSIGNED NULL DEFAULT NULL ,
  `nick` VARCHAR(255) NOT NULL ,
  PRIMARY KEY (`id`) )
ENGINE = MyISAM
DEFAULT CHARACTER SET = utf8
COMMENT = 'IRC Nicks';


-- -----------------------------------------------------
-- Table `txircd`.`irc_tokens`
-- -----------------------------------------------------
DROP TABLE IF EXISTS `txircd`.`irctokens` ;

CREATE  TABLE IF NOT EXISTS `txircd`.`irctokens` (
  `id` INT(10) UNSIGNED NOT NULL AUTO_INCREMENT ,
  `donor_id` INT(10) UNSIGNED NULL DEFAULT NULL ,
  `token` VARCHAR(64) NOT NULL ,
  `ip` VARCHAR(45) NOT NULL ,
  PRIMARY KEY (`id`) ,
  UNIQUE INDEX `token_UNIQUE` (`token` ASC) ,
  INDEX `ip` (`ip` ASC) )
ENGINE = MyISAM
DEFAULT CHARACTER SET = utf8
COMMENT = 'IRC Tokens';

-- -----------------------------------------------------
-- Test data
-- -----------------------------------------------------
INSERT INTO `txircd`.`prizes`(`name`) VALUES("Ashton's Love");
INSERT INTO `txircd`.`prizes`(`name`) VALUES("Kroze's Soul");
INSERT INTO `txircd`.`prizes`(`name`) VALUES("Kathleen's Endurance");
INSERT INTO `txircd`.`prizes`(`name`) VALUES("Alex's Derp");
INSERT INTO `txircd`.`prizes`(`name`) VALUES("James's Patience");
INSERT INTO `txircd`.`prizes`(`name`) VALUES("Morgan's Charisma");
INSERT INTO `txircd`.`prizes`(`name`) VALUES("Paul's Beard");

SET SQL_MODE=@OLD_SQL_MODE;
SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS;
SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS;
